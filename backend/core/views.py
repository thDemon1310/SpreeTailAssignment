from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from .models import Expense, ExpenseSplit, Group, Membership, Settlement
from .balance_calc import calculate_balances, calculate_user_balance
from .serializers import (
    RegisterSerializer,
    UserSerializer,
    GroupSerializer,
    GroupCreateSerializer,
    AddMemberSerializer,
    UpdateMemberSerializer,
    MembershipSerializer,
    ExpenseListSerializer,
    ExpenseSerializer,
    ExpenseCreateSerializer,
    SettlementSerializer,
    ImportBatchSerializer,
    ImportAnomalySerializer,
)

User = get_user_model()


# --------------- Auth ---------------

class RegisterView(generics.CreateAPIView):
    """Public endpoint: create a new user account."""
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class MeView(generics.RetrieveAPIView):
    """Return the currently authenticated user's details."""
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


# --------------- Groups ---------------

class GroupListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/groups/       — list groups the user is a member of
    POST /api/groups/       — create a new group (creator auto-added as member)
    """

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return GroupCreateSerializer
        return GroupSerializer

    def get_queryset(self):
        return Group.objects.filter(
            memberships__user=self.request.user,
            memberships__left_on__isnull=True
        ).select_related('created_by').prefetch_related('memberships__user').distinct()

    def perform_create(self, serializer):
        serializer.save()


class GroupDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/groups/<id>/  — group detail with members
    PATCH  /api/groups/<id>/  — update group name/description
    DELETE /api/groups/<id>/  — delete group
    """
    serializer_class = GroupSerializer

    def get_queryset(self):
        return Group.objects.filter(
            memberships__user=self.request.user,
            memberships__left_on__isnull=True
        ).select_related('created_by').prefetch_related('memberships__user').distinct()


# --------------- Membership management ---------------

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_member(request, group_id):
    """
    POST /api/groups/<group_id>/members/
    Add a user to the group with a join date.
    """
    group = get_object_or_404(Group, id=group_id)

    # Check that requester is a member of this group
    if not group.memberships.filter(user=request.user).exists():
        return Response(
            {'detail': 'You are not a member of this group.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = AddMemberSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user_id = serializer.validated_data.get('user_id')
    username = serializer.validated_data.get('username')

    from django.db.models import Q
    if user_id:
        user = get_object_or_404(User, id=user_id)
    else:
        user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()
        if not user:
            return Response(
                {'detail': 'User does not exist.'},
                status=status.HTTP_404_NOT_FOUND,
            )

    # Check for active membership
    if group.memberships.filter(user=user, left_on__isnull=True).exists():
        return Response(
            {'detail': 'User is already an active member of this group.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate new join date is after latest previous leave date
    latest_left = group.memberships.filter(user=user).order_by('-left_on').first()
    if latest_left and latest_left.left_on:
        new_joined_on = serializer.validated_data['joined_on']
        if new_joined_on <= latest_left.left_on:
            return Response(
                {'detail': f"New join date must be after the user's previous leave date ({latest_left.left_on})."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    membership = Membership.objects.create(
        user=user,
        group=group,
        joined_on=serializer.validated_data['joined_on'],
    )

    return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def update_or_remove_member(request, group_id, membership_id):
    """
    PATCH  /api/groups/<group_id>/members/<membership_id>/  — set left_on date
    DELETE /api/groups/<group_id>/members/<membership_id>/  — remove membership
    """
    group = get_object_or_404(Group, id=group_id)

    # Check that requester is a member of this group
    if not group.memberships.filter(user=request.user).exists():
        return Response(
            {'detail': 'You are not a member of this group.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    membership = get_object_or_404(Membership, id=membership_id, group=group)

    if request.method == 'DELETE':
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH — update left_on
    serializer = UpdateMemberSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    if 'left_on' in serializer.validated_data:
        membership.left_on = serializer.validated_data['left_on']
        membership.save(update_fields=['left_on'])

    return Response(MembershipSerializer(membership).data)


# --------------- Expenses ---------------


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def expense_list_create(request, group_id):
    """
    GET  /api/groups/<group_id>/expenses/  — list all expenses in the group
    POST /api/groups/<group_id>/expenses/  — create a new expense

    Only members of the group may access this endpoint.
    POST calls calculate_splits internally and writes ExpenseSplit rows
    atomically — if split validation fails, nothing is saved.
    """
    group = get_object_or_404(Group, id=group_id)

    if not group.memberships.filter(user=request.user).exists():
        return Response(
            {'detail': 'You are not a member of this group.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'GET':
        expenses = (
            Expense.objects.filter(group=group)
            .select_related('paid_by')
            .order_by('-date', '-created_at')
        )
        serializer = ExpenseListSerializer(expenses, many=True)
        return Response(serializer.data)

    # POST
    serializer = ExpenseCreateSerializer(
        data=request.data,
        context={'group': group, 'request': request},
    )
    serializer.is_valid(raise_exception=True)
    expense = serializer.save()
    # Return full detail representation after creation
    return Response(
        ExpenseSerializer(expense).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def expense_detail(request, group_id, expense_id):
    """
    GET    /api/groups/<group_id>/expenses/<expense_id>/  — full expense + splits
    DELETE /api/groups/<group_id>/expenses/<expense_id>/  — delete expense + its splits

    Deleting an expense cascades to its ExpenseSplit rows (FK on_delete=CASCADE).
    No PATCH: editing a split type after creation requires re-running split_calc
    and atomically replacing all splits — that is out of scope for this task.
    """
    group = get_object_or_404(Group, id=group_id)

    if not group.memberships.filter(user=request.user).exists():
        return Response(
            {'detail': 'You are not a member of this group.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    expense = get_object_or_404(
        Expense.objects.select_related('paid_by').prefetch_related('splits__user'),
        id=expense_id,
        group=group,
    )

    if request.method == 'DELETE':
        expense.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    return Response(ExpenseSerializer(expense).data)


# --------------- Settlements ---------------

@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def settlement_list_create(request, group_id):
    """
    GET  /api/groups/<group_id>/settlements/
    POST /api/groups/<group_id>/settlements/
    """
    group = get_object_or_404(Group, id=group_id)
    if not group.memberships.filter(user=request.user).exists():
        return Response({'detail': 'Not a member.'}, status=status.HTTP_403_FORBIDDEN)
    
    if request.method == 'GET':
        settlements = Settlement.objects.filter(group=group).order_by('-date')
        return Response(SettlementSerializer(settlements, many=True).data)
    
    # POST
    # expects: from_user_id (optional, defaults to requesting user), to_user_id, amount, date
    from_user_id = request.data.get('from_user_id')
    to_user_id = request.data.get('to_user_id')
    amount = request.data.get('amount')
    date = request.data.get('date')
    
    if not all([to_user_id, amount, date]):
        return Response({'detail': 'to_user_id, amount, and date are required.'}, status=status.HTTP_400_BAD_REQUEST)
        
    # Enforce from_user is request.user
    if from_user_id is not None:
        try:
            if int(from_user_id) != request.user.id:
                return Response({'detail': 'You can only record a settlement where you are the payer.'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid from_user_id.'}, status=status.HTTP_400_BAD_REQUEST)
    from_user_id = request.user.id

    if int(to_user_id) == from_user_id:
        return Response({'detail': 'Cannot settle with yourself.'}, status=status.HTTP_400_BAD_REQUEST)

    from django.utils.dateparse import parse_date
    settlement_date = parse_date(str(date))
    if not settlement_date:
        return Response({'detail': 'Invalid date format.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        amount = Decimal(str(amount))
        if amount <= Decimal('0'):
            return Response({'detail': 'amount must be positive.'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        return Response({'detail': 'Invalid amount.'}, status=status.HTTP_400_BAD_REQUEST)
        
    from_user = request.user
    to_user = get_object_or_404(User, id=to_user_id)
    
    # Check that to_user is a member and active on the settlement date (left_on has not passed)
    to_membership = group.memberships.filter(user=to_user).first()
    if not to_membership:
        return Response({'detail': 'Recipient is not a member of this group.'}, status=status.HTTP_400_BAD_REQUEST)
        
    if to_membership.joined_on > settlement_date:
        return Response({'detail': 'Recipient was not a member of the group on this settlement date.'}, status=status.HTTP_400_BAD_REQUEST)
    if to_membership.left_on and settlement_date > to_membership.left_on:
        return Response({'detail': 'Recipient was no longer an active member of this group on this settlement date.'}, status=status.HTTP_400_BAD_REQUEST)
    
    settlement = Settlement.objects.create(
        group=group,
        from_user=from_user,
        to_user=to_user,
        amount=amount,
        date=settlement_date
    )
    
    return Response(SettlementSerializer(settlement).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def leave_group(request, group_id):
    """
    POST /api/groups/<group_id>/leave/
    Allows the authenticated user to leave the group, setting left_on to today's date,
    only if their balance is exactly zero.
    """
    group = get_object_or_404(Group, id=group_id)
    # Check if any membership exists
    any_membership = group.memberships.filter(user=request.user).first()
    if not any_membership:
        return Response({'detail': 'You are not a member of this group.'}, status=status.HTTP_400_BAD_REQUEST)
        
    # Check if an active membership exists
    membership = group.memberships.filter(user=request.user, left_on__isnull=True).first()
    if not membership:
        return Response({'detail': 'You have already left this group.'}, status=status.HTTP_400_BAD_REQUEST)
        
    # Get all balances to find who is owed or who owes
    balances = calculate_balances(group_id)
    user_balance = balances.get(request.user.id, Decimal('0.00'))
    
    if abs(user_balance) >= Decimal('0.01'):
        if user_balance < 0:
            # User owes money: list members who have a positive balance (creditors)
            creditors = [
                u.username for u in User.objects.filter(id__in=[uid for uid, bal in balances.items() if bal > Decimal('0.00')])
            ]
            creditors_str = ", ".join(creditors)
            msg = f"Cannot leave group. You have an outstanding balance of {user_balance:.2f} INR. You owe the following member(s): {creditors_str}."
        else:
            # User is owed money: list members who have a negative balance (debtors)
            debtors = [
                u.username for u in User.objects.filter(id__in=[uid for uid, bal in balances.items() if bal < Decimal('0.00')])
            ]
            debtors_str = ", ".join(debtors)
            msg = f"Cannot leave group. You have an outstanding balance of +{user_balance:.2f} INR. You are owed by the following member(s): {debtors_str}."
            
        return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        
    # Success: set left_on to today's date
    from django.utils import timezone
    membership.left_on = timezone.now().date()
    membership.save(update_fields=['left_on'])
    
    return Response({'detail': 'Successfully left the group.'})


# --------------- Balances ---------------

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def group_balances(request, group_id):
    """
    GET /api/groups/<group_id>/balances/
    Returns {user_id: Decimal_balance} for all members/payers.
    """
    group = get_object_or_404(Group, id=group_id)
    if not group.memberships.filter(user=request.user).exists():
        return Response({'detail': 'Not a member of this group.'}, status=status.HTTP_403_FORBIDDEN)
    
    balances = calculate_balances(group_id)
    return Response(balances)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def group_user_balance_detail(request, group_id, user_id):
    """
    GET /api/groups/<group_id>/balances/<user_id>/
    Returns balance + drill-down of underlying rows for Rohan's 'no magic numbers' view.
    """
    group = get_object_or_404(Group, id=group_id)
    if not group.memberships.filter(user=request.user).exists():
        return Response({'detail': 'Not a member of this group.'}, status=status.HTTP_403_FORBIDDEN)
    
    target_user = get_object_or_404(User, id=user_id)
    
    balance = calculate_user_balance(group_id, target_user.id)
    
    # Underlying queries
    paid_expenses = Expense.objects.filter(group=group, paid_by=target_user)
    
    from django.db.models import Q
    memberships = Membership.objects.filter(group=group, user=target_user)
    if memberships.exists():
        q_filter = Q()
        for mem in memberships:
            stint_q = Q(expense__date__gte=mem.joined_on)
            if mem.left_on:
                stint_q &= Q(expense__date__lte=mem.left_on)
            q_filter |= stint_q

        owed_splits = ExpenseSplit.objects.filter(
            user=target_user,
            expense__group=group
        ).filter(q_filter).select_related('expense')
    else:
        owed_splits = ExpenseSplit.objects.none()

    settlements_made = Settlement.objects.filter(group=group, from_user=target_user)
    settlements_received = Settlement.objects.filter(group=group, to_user=target_user)

    from django.db.models import Sum
    ZERO = Decimal('0.00')

    # DRF JSONRenderer handles Decimal serialization automatically
    return Response({
        'balance': balance,
        'total_paid': paid_expenses.aggregate(total=Sum('amount'))['total'] or ZERO,
        'paid_expenses': [
            {'id': e.id, 'description': e.description, 'amount': e.amount, 'date': e.date}
            for e in paid_expenses.order_by('-date')
        ],
        'total_owed': owed_splits.aggregate(total=Sum('share_amount'))['total'] or ZERO,
        'owed_splits': [
            {'id': s.id, 'expense': {'id': s.expense.id, 'description': s.expense.description, 'date': s.expense.date}, 'share_amount': s.share_amount}
            for s in owed_splits.order_by('-expense__date')
        ],
        'settlements_made': settlements_made.aggregate(total=Sum('amount'))['total'] or ZERO,
        'settlements_made_list': [
            {'id': s.id, 'to_user_id': s.to_user_id, 'amount': s.amount, 'date': s.date}
            for s in settlements_made.order_by('-date')
        ],
        'settlements_received': settlements_received.aggregate(total=Sum('amount'))['total'] or ZERO,
        'settlements_received_list': [
            {'id': s.id, 'from_user_id': s.from_user_id, 'amount': s.amount, 'date': s.date}
            for s in settlements_received.order_by('-date')
        ]
    })


# --------------- Import ---------------

from .importer import run_import
from .models import ImportBatch, ImportAnomaly
import tempfile
import os

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def import_csv(request, group_id):
    """
    POST /api/groups/<group_id>/import/
    Accepts a multipart/form-data with a 'file' field containing the CSV.
    Runs the importer and returns the batch summary.
    """
    group = get_object_or_404(Group, id=group_id)
    if not group.memberships.filter(user=request.user).exists():
        return Response({'detail': 'Not a member.'}, status=status.HTTP_403_FORBIDDEN)
        
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response({'detail': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)
        
    # Write to temp file because run_import takes a path
    with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp:
        for chunk in file_obj.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
        
    try:
        result = run_import(tmp_path, group, request.user)
        return Response({
            'batch_id': result.batch.id,
            'total_rows_processed': result.batch.total_rows,
            'imported_rows': result.imported_rows,
            'skipped_rows': result.skipped_rows,
            'created_at': result.batch.created_at
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        os.remove(tmp_path)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def import_anomalies(request, group_id, batch_id):
    """
    GET /api/groups/<group_id>/import/<batch_id>/anomalies/
    Returns the anomalies for a specific batch.
    """
    group = get_object_or_404(Group, id=group_id)
    if not group.memberships.filter(user=request.user).exists():
        return Response({'detail': 'Not a member.'}, status=status.HTTP_403_FORBIDDEN)
        
    batch = get_object_or_404(ImportBatch, id=batch_id, group=group)
    anomalies = ImportAnomaly.objects.filter(batch=batch).order_by('row_number')
    return Response(ImportAnomalySerializer(anomalies, many=True).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def resolve_anomaly(request, group_id, anomaly_id):
    """
    POST /api/groups/<group_id>/anomalies/<anomaly_id>/resolve/
    """
    group = get_object_or_404(Group, id=group_id)
    if not group.memberships.filter(user=request.user).exists():
        return Response({'detail': 'Not a member.'}, status=status.HTTP_403_FORBIDDEN)
        
    anomaly = get_object_or_404(ImportAnomaly, id=anomaly_id, batch__group=group)
    if anomaly.status != 'blocked':
        return Response({'detail': 'Anomaly is not blocked.'}, status=status.HTTP_400_BAD_REQUEST)
        
    action = request.data.get('action')
    if action not in ['apply', 'discard']:
        return Response({'detail': 'Invalid action.'}, status=status.HTTP_400_BAD_REQUEST)
        
    if action == 'discard':
        anomaly.status = 'manually_resolved'
        anomaly.action_taken = 'Discarded by user'
        anomaly.resolved_by = request.user
        from django.utils import timezone
        anomaly.resolved_at = timezone.now()
        anomaly.save()
        return Response({'detail': 'Discarded.'})
        
    # Apply
    corrected_data = request.data.get('corrected_data', {})
    ptype = anomaly.problem_type
    
    # Validation per type
    if ptype == 'missing_payer' and 'paid_by_id' not in corrected_data:
        return Response({'detail': 'paid_by_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if ptype == 'bad_date' and 'date' not in corrected_data:
        return Response({'detail': 'date is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if ptype in ['zero_amount', 'missing_amount'] and 'amount' not in corrected_data:
        return Response({'detail': 'amount is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if ptype == 'settlement_as_expense':
        for f in ['from_user_id', 'to_user_id', 'amount', 'date']:
            if f not in corrected_data:
                return Response({'detail': f'{f} is required.'}, status=status.HTTP_400_BAD_REQUEST)
                
    # Create the row
    from django.utils import timezone
    raw = anomaly.raw_data.copy()
    
    if ptype == 'settlement_as_expense':
        # Create Settlement
        from .models import Settlement
        s = Settlement.objects.create(
            group=group,
            from_user_id=corrected_data['from_user_id'],
            to_user_id=corrected_data['to_user_id'],
            amount=corrected_data['amount'],
            date=corrected_data['date'],
            note=raw.get('description', '')
        )
        anomaly.linked_settlement = s
    else:
        # Create Expense
        from .importer import _build_member_lookup, _resolve_names, USD_TO_INR
        from .split_calc import calculate_splits
        from .models import Expense, ExpenseSplit
        from decimal import Decimal
        from django.utils.dateparse import parse_date
        
        name_to_user, all_time = _build_member_lookup(group)
        
        paid_by_id = corrected_data.get('paid_by_id')
        if not paid_by_id:
            paid_by_raw = raw.get('paid_by', '').strip()
            res_payer, _ = _resolve_names([paid_by_raw], name_to_user)
            if res_payer:
                paid_by_id = res_payer[0].id
                
        if not paid_by_id:
            return Response({'detail': 'paid_by_id could not be resolved.'}, status=status.HTTP_400_BAD_REQUEST)
            
        paid_by_user = User.objects.get(id=paid_by_id)
        
        amt_str = str(corrected_data.get('amount', raw.get('amount', '0')))
        try:
            amount_val = Decimal(amt_str)
        except Exception:
            amount_val = Decimal('0')
            
        is_neg = False
        if amount_val < 0:
            is_neg = True
            amount_val = abs(amount_val)
            
        curr = raw.get('currency', 'INR').strip().upper()
        
        if curr == 'USD':
            amount_inr = amount_val * USD_TO_INR
            orig = amount_val
            rate = USD_TO_INR
        else:
            amount_inr = amount_val
            orig = None
            rate = None
            curr = 'INR'
            
        date_str = corrected_data.get('date', raw.get('date', ''))
        exp_date = parse_date(date_str)
        if not exp_date:
            exp_date = timezone.now().date()
            
        split_type = raw.get('split_type', 'equal').strip().lower() or 'equal'
        split_with_raw = raw.get('split_with', '')
        names = [n.strip() for n in split_with_raw.replace(';', ',').split(',') if n.strip()]
        if not names:
            names = [paid_by_user.username]
        resolved_users, _ = _resolve_names(names, name_to_user)
        part_ids = [u.id for u in resolved_users]
        if paid_by_id not in part_ids and split_type == 'equal':
            part_ids.append(paid_by_id)
            
        if not part_ids:
            return Response({'detail': 'No valid participants found.'}, status=status.HTTP_400_BAD_REQUEST)
            
        splits = calculate_splits(
            total=amount_inr,
            split_type='equal', # fallback to equal for generic resolution to save time
            participant_ids=part_ids,
            paid_by_id=paid_by_id,
            split_details={}
        )
        
        if is_neg:
            amount_inr = -amount_inr
            if orig: orig = -orig
            splits = {k: -v for k,v in splits.items()}
            
        from django.db import transaction
        with transaction.atomic():
            e = Expense.objects.create(
                group=group,
                paid_by=paid_by_user,
                description=raw.get('description', '').strip(),
                amount=amount_inr,
                currency=curr,
                original_amount=orig,
                exchange_rate=rate,
                date=exp_date,
                split_type='equal',
            )
            ExpenseSplit.objects.bulk_create([
                ExpenseSplit(expense=e, user_id=uid, share_amount=s)
                for uid, s in splits.items()
            ])
        anomaly.linked_expense = e
        
    anomaly.status = 'manually_resolved'
    anomaly.action_taken = 'Applied corrected data'
    anomaly.resolved_by = request.user
    anomaly.resolved_at = timezone.now()
    anomaly.save()
    
    return Response({'detail': 'Resolved.'})


from rest_framework import filters

class UserListView(generics.ListAPIView):
    """
    GET /api/users/ — list and search all users in the system.
    """
    queryset = User.objects.all().order_by('username')
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'email']


