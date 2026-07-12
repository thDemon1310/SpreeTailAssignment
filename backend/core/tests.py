from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


class RegisterViewTest(TestCase):
    """Tests for POST /api/auth/register/"""

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/auth/register/'

    def test_register_success(self):
        resp = self.client.post(self.url, {
            'username': 'aisha',
            'email': 'aisha@example.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['username'], 'aisha')
        self.assertNotIn('password', resp.data)
        self.assertTrue(User.objects.filter(username='aisha').exists())

    def test_register_duplicate_username(self):
        User.objects.create_user('aisha', 'a@example.com', 'TestPass123!')
        resp = self.client.post(self.url, {
            'username': 'aisha',
            'email': 'aisha2@example.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_weak_password(self):
        resp = self.client.post(self.url, {
            'username': 'rohan',
            'email': 'rohan@example.com',
            'password': '123',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TokenViewTest(TestCase):
    """Tests for POST /api/token/ and /api/token/refresh/"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            'aisha', 'aisha@example.com', 'TestPass123!'
        )

    def test_obtain_token(self):
        resp = self.client.post('/api/token/', {
            'username': 'aisha',
            'password': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

    def test_obtain_token_wrong_password(self):
        resp = self.client.post('/api/token/', {
            'username': 'aisha',
            'password': 'WrongPass!',
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token(self):
        login_resp = self.client.post('/api/token/', {
            'username': 'aisha',
            'password': 'TestPass123!',
        })
        refresh = login_resp.data['refresh']
        resp = self.client.post('/api/token/refresh/', {'refresh': refresh})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)


class MeViewTest(TestCase):
    """Tests for GET /api/auth/me/"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            'aisha', 'aisha@example.com', 'TestPass123!'
        )

    def test_me_unauthenticated(self):
        resp = self.client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_authenticated(self):
        login_resp = self.client.post('/api/token/', {
            'username': 'aisha',
            'password': 'TestPass123!',
        })
        token = login_resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        resp = self.client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['username'], 'aisha')


# --------------- Group CRUD ---------------

from datetime import date
from core.models import Group, Membership


class GroupCRUDTest(TestCase):
    """Tests for Group create/list/detail/update/delete."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user('aisha', 'a@example.com', 'TestPass123!')
        login = self.client.post('/api/token/', {'username': 'aisha', 'password': 'TestPass123!'})
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')

    def test_create_group(self):
        resp = self.client.post('/api/groups/', {'name': 'The Flat', 'description': 'Our place'})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'The Flat')
        # Creator should be auto-added as member
        group = Group.objects.get(id=resp.data['id'])
        self.assertTrue(group.memberships.filter(user=self.user).exists())

    def test_list_groups(self):
        self.client.post('/api/groups/', {'name': 'Flat A'})
        self.client.post('/api/groups/', {'name': 'Flat B'})
        resp = self.client.get('/api/groups/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 2)

    def test_group_detail(self):
        create_resp = self.client.post('/api/groups/', {'name': 'The Flat'})
        group_id = create_resp.data['id']
        resp = self.client.get(f'/api/groups/{group_id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'The Flat')
        self.assertEqual(len(resp.data['memberships']), 1)

    def test_update_group(self):
        create_resp = self.client.post('/api/groups/', {'name': 'Old Name'})
        group_id = create_resp.data['id']
        resp = self.client.patch(f'/api/groups/{group_id}/', {'name': 'New Name'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'New Name')

    def test_delete_group(self):
        create_resp = self.client.post('/api/groups/', {'name': 'To Delete'})
        group_id = create_resp.data['id']
        resp = self.client.delete(f'/api/groups/{group_id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Group.objects.filter(id=group_id).exists())


class MembershipManagementTest(TestCase):
    """Tests for adding/removing members with dates."""

    def setUp(self):
        self.client = APIClient()
        self.aisha = User.objects.create_user('aisha', 'a@example.com', 'TestPass123!')
        self.rohan = User.objects.create_user('rohan', 'r@example.com', 'TestPass123!')
        self.priya = User.objects.create_user('priya', 'p@example.com', 'TestPass123!')

        login = self.client.post('/api/token/', {'username': 'aisha', 'password': 'TestPass123!'})
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')

        resp = self.client.post('/api/groups/', {'name': 'The Flat'})
        self.group_id = resp.data['id']

    def test_add_member(self):
        resp = self.client.post(f'/api/groups/{self.group_id}/members/', {
            'user_id': self.rohan.id,
            'joined_on': '2026-02-01',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['username'], 'rohan')
        self.assertEqual(resp.data['joined_on'], '2026-02-01')

    def test_add_member_by_username(self):
        resp = self.client.post(f'/api/groups/{self.group_id}/members/', {
            'username': 'rohan',
            'joined_on': '2026-02-01',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['username'], 'rohan')
        self.assertEqual(resp.data['joined_on'], '2026-02-01')

    def test_add_member_by_email(self):
        self.rohan.email = 'rohan@example.com'
        self.rohan.save()
        resp = self.client.post(f'/api/groups/{self.group_id}/members/', {
            'username': 'rohan@example.com',
            'joined_on': '2026-02-01',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['username'], 'rohan')
        self.assertEqual(resp.data['joined_on'], '2026-02-01')

    def test_add_member_nonexistent_username(self):
        resp = self.client.post(f'/api/groups/{self.group_id}/members/', {
            'username': 'nonexistentuser',
            'joined_on': '2026-02-01',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('User does not exist.', str(resp.data))

    def test_add_duplicate_member(self):
        self.client.post(f'/api/groups/{self.group_id}/members/', {
            'user_id': self.rohan.id, 'joined_on': '2026-02-01',
        })
        resp = self.client.post(f'/api/groups/{self.group_id}/members/', {
            'user_id': self.rohan.id, 'joined_on': '2026-03-01',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_left_on(self):
        add_resp = self.client.post(f'/api/groups/{self.group_id}/members/', {
            'user_id': self.rohan.id, 'joined_on': '2026-02-01',
        })
        membership_id = add_resp.data['id']
        resp = self.client.patch(
            f'/api/groups/{self.group_id}/members/{membership_id}/',
            {'left_on': '2026-03-31'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['left_on'], '2026-03-31')

    def test_remove_member(self):
        add_resp = self.client.post(f'/api/groups/{self.group_id}/members/', {
            'user_id': self.rohan.id, 'joined_on': '2026-02-01',
        })
        membership_id = add_resp.data['id']
        resp = self.client.delete(f'/api/groups/{self.group_id}/members/{membership_id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_non_member_cannot_add(self):
        """A user who isn't in the group can't add others."""
        login = self.client.post('/api/token/', {'username': 'rohan', 'password': 'TestPass123!'})
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')
        resp = self.client.post(f'/api/groups/{self.group_id}/members/', {
            'user_id': self.priya.id, 'joined_on': '2026-02-01',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
