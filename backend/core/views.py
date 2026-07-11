from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from .models import Group, Membership
from .serializers import (
    RegisterSerializer,
    UserSerializer,
    GroupSerializer,
    GroupCreateSerializer,
    AddMemberSerializer,
    UpdateMemberSerializer,
    MembershipSerializer,
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
