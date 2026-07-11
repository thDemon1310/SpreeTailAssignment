from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

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

from .models import Group, Membership


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
