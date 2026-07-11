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
