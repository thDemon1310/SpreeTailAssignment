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
            memberships__user=self.request.user
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
            memberships__user=self.request.user
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

    user = get_object_or_404(User, id=serializer.validated_data['user_id'])

    # Check for existing membership
    if group.memberships.filter(user=user).exists():
        return Response(
            {'detail': 'User is already a member of this group.'},
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
    
    membership = Membership.objects.filter(group=group, user=target_user).first()
    if membership:
        owed_splits = ExpenseSplit.objects.filter(
            user=target_user,
            expense__group=group,
            expense__date__gte=membership.joined_on
        ).select_related('expense')
        if membership.left_on:
            owed_splits = owed_splits.filter(expense__date__lte=membership.left_on)
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

