from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration. Validates password strength."""

    password = serializers.CharField(
        write_only=True,
        min_length=8,
        validators=[validate_password],
    )

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password')
        extra_kwargs = {
            'email': {'required': True},
        }

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
        )
        return user


class UserSerializer(serializers.ModelSerializer):
    """Read-only serializer for user details."""

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name')
        read_only_fields = fields


# --------------- Group / Membership ---------------

from .models import Expense, ExpenseSplit, Group, Membership, Settlement


class MembershipSerializer(serializers.ModelSerializer):
    """Serializer for membership records — includes user details read-only."""
    username = serializers.CharField(source='user.username', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)

    class Meta:
        model = Membership
        fields = ('id', 'user_id', 'username', 'joined_on', 'left_on')
        read_only_fields = ('id', 'user_id', 'username')


class GroupSerializer(serializers.ModelSerializer):
    """Full group representation with nested membership list."""
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    memberships = MembershipSerializer(many=True, read_only=True)

    class Meta:
        model = Group
        fields = ('id', 'name', 'description', 'created_by', 'created_by_username',
                  'memberships', 'created_at')
        read_only_fields = ('id', 'created_by', 'created_by_username', 'created_at')


class GroupCreateSerializer(serializers.ModelSerializer):
    """Serializer for group creation — auto-sets created_by from request user."""

    class Meta:
        model = Group
        fields = ('id', 'name', 'description')

    def create(self, validated_data):
        user = self.context['request'].user
        group = Group.objects.create(created_by=user, **validated_data)
        # Auto-add creator as the first member, joined today
        from django.utils import timezone
        Membership.objects.create(
            user=user,
            group=group,
            joined_on=timezone.now().date(),
        )
        return group


class AddMemberSerializer(serializers.Serializer):
    """Serializer for adding a member to a group."""
    user_id = serializers.IntegerField()
    joined_on = serializers.DateField()

    def validate_user_id(self, value):
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("User does not exist.")
        return value


class UpdateMemberSerializer(serializers.Serializer):
    """Serializer for updating membership (e.g. setting left_on)."""
    left_on = serializers.DateField(required=False, allow_null=True)


# --------------- Expense / ExpenseSplit ---------------


class ExpenseSplitSerializer(serializers.ModelSerializer):
    """
    Read-only representation of one person's share of an expense.
    Included nested inside ExpenseSerializer so the frontend can display
    the full breakdown without a second request.
    """

    username = serializers.CharField(source='user.username', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)

    class Meta:
        model = ExpenseSplit
        fields = ('id', 'user_id', 'username', 'share_amount')
        read_only_fields = fields


class ExpenseSerializer(serializers.ModelSerializer):
    """
    Full read-only expense representation.

    Returns all fields plus nested splits list and paid_by username so
    the frontend never needs to do a second lookup for the common case.
    """

    paid_by_id = serializers.IntegerField(source='paid_by.id', read_only=True)
    paid_by_username = serializers.CharField(source='paid_by.username', read_only=True)
    splits = ExpenseSplitSerializer(many=True, read_only=True)

    class Meta:
        model = Expense
        fields = (
            'id',
            'group',
            'paid_by_id',
            'paid_by_username',
            'description',
            'amount',
            'currency',
            'original_amount',
            'exchange_rate',
            'date',
            'split_type',
            'is_settlement',
            'notes',
            'splits',
            'created_at',
        )
        read_only_fields = fields


class ExpenseListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for list views — omits nested splits to keep
    list responses compact. Use ExpenseSerializer for /expenses/<id>/.
    """

    paid_by_username = serializers.CharField(source='paid_by.username', read_only=True)

    class Meta:
        model = Expense
        fields = (
            'id',
            'paid_by_username',
            'description',
            'amount',
            'currency',
            'date',
            'split_type',
            'is_settlement',
            'created_at',
        )
        read_only_fields = fields


class ExpenseCreateSerializer(serializers.Serializer):
    """
    Write-only serializer for creating an expense.

    Validates inputs, calls calculate_splits, and saves both the Expense
    and all ExpenseSplit rows in a single DB transaction. If split_calc
    raises a SplitCalcError the whole request is rolled back.

    Expected request body (JSON):
    {
        "description":    "Dinner at Marina",
        "amount":         "3200.00",
        "currency":       "INR",               # optional, default INR
        "original_amount": null,               # optional
        "exchange_rate":   null,               # optional
        "date":           "2026-02-08",
        "split_type":     "equal",
        "paid_by_id":     1,
        "participant_ids": [1, 2, 3],
        "split_details":  {},                  # ignored for equal; required content for others
        "notes":          ""                   # optional
    }
    """

    # --- required fields ---
    description = serializers.CharField(max_length=500)
    amount = serializers.DecimalField(max_digits=12, decimal_places=5)
    date = serializers.DateField()
    split_type = serializers.ChoiceField(choices=Expense.SPLIT_TYPE_CHOICES)
    paid_by_id = serializers.IntegerField()
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text='PKs of users who share this expense. Must be non-empty.',
    )
    split_details = serializers.DictField(
        child=serializers.CharField(),  # parsed to Decimal in validate()
        required=False,
        default=dict,
        help_text='Dict of {user_id_str: value_str} for unequal/percentage/shares split types.',
    )

    # --- optional fields ---
    currency = serializers.CharField(max_length=3, required=False, default='INR')
    original_amount = serializers.DecimalField(
        max_digits=12, decimal_places=5, required=False, allow_null=True, default=None
    )
    exchange_rate = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True, default=None
    )
    notes = serializers.CharField(required=False, default='', allow_blank=True)

    def validate_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError('amount must be positive.')
        return value

    def validate_paid_by_id(self, value):
        User = get_user_model()
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError(f'User {value} does not exist.')
        return value

    def validate(self, data):
        """Cross-field validation and split_details key coercion."""
        User = get_user_model()

        # Validate all participant_ids exist
        participant_ids = data['participant_ids']
        existing_ids = set(
            User.objects.filter(id__in=participant_ids).values_list('id', flat=True)
        )
        missing = set(participant_ids) - existing_ids
        if missing:
            raise serializers.ValidationError(
                {'participant_ids': f'Unknown user id(s): {sorted(missing)}'}
            )

        # Coerce split_details keys to int and values to Decimal
        raw_details = data.get('split_details', {})
        try:
            coerced = {int(k): Decimal(str(v)) for k, v in raw_details.items()}
        except (ValueError, TypeError) as exc:
            raise serializers.ValidationError(
                {'split_details': f'All keys must be integers and values must be numbers: {exc}'}
            )
        data['split_details'] = coerced
        return data

    def create(self, validated_data):
        """
        Save Expense + ExpenseSplit rows atomically.

        Calls calculate_splits (pure function, raises SplitCalcError on bad
        input) then writes every row in one transaction. If anything fails,
        nothing is written.
        """
        from .split_calc import calculate_splits, SplitCalcError

        group = self.context['group']
        User = get_user_model()

        paid_by_id = validated_data['paid_by_id']
        participant_ids = validated_data['participant_ids']
        split_details = validated_data['split_details']
        total = validated_data['amount']
        split_type = validated_data['split_type']

        # Compute splits before touching the DB
        try:
            splits = calculate_splits(
                total=total,
                split_type=split_type,
                participant_ids=participant_ids,
                paid_by_id=paid_by_id,
                split_details=split_details,
            )
        except SplitCalcError as exc:
            raise serializers.ValidationError({'split_details': str(exc)})

        paid_by_user = User.objects.get(id=paid_by_id)

        with transaction.atomic():
            expense = Expense.objects.create(
                group=group,
                paid_by=paid_by_user,
                description=validated_data['description'],
                amount=total,
                currency=validated_data.get('currency', 'INR'),
                original_amount=validated_data.get('original_amount'),
                exchange_rate=validated_data.get('exchange_rate'),
                date=validated_data['date'],
                split_type=split_type,
                notes=validated_data.get('notes', ''),
            )
            ExpenseSplit.objects.bulk_create([
                ExpenseSplit(expense=expense, user_id=uid, share_amount=share)
                for uid, share in splits.items()
            ])

        return expense


class SettlementSerializer(serializers.ModelSerializer):
    """Serializer for Settlement rows."""
    from_username = serializers.CharField(source='from_user.username', read_only=True)
    to_username = serializers.CharField(source='to_user.username', read_only=True)

    class Meta:
        model = Settlement
        fields = (
            'id', 'group', 'from_user', 'from_username',
            'to_user', 'to_username',
            'amount', 'date', 'created_at'
        )
        read_only_fields = ('id', 'group', 'from_username', 'to_username', 'created_at')
