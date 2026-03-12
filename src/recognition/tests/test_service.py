import os
import sys
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

# --- THE PATH FIX ---
# This forces Python to recognize D:\INTERN\AS-4_backend as the root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, PROJECT_ROOT)

# --- STRICT ABSOLUTE IMPORTS ---
# Notice how we explicitly start from 'src' for everything now
from src.recognition.tests.conftest import make_user, make_review
import src.recognition.service as service
from src.recognition.service import RecognitionService

class TestGetReview(unittest.IsolatedAsyncioTestCase):

    async def test_reviewer_can_access_own_review(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch.object(service.db.reviews, "find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        # Replaced standard asserts with unittest asserts
        self.assertIsInstance(result, dict)
        self.assertEqual(result["reviewer_id"], "user-1")

    async def test_unrelated_employee_gets_403(self):
        user   = make_user(user_id="stranger", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch.object(service.db.reviews, "find_unique", AsyncMock(return_value=review)):
            # unittest's exception context manager
            with self.assertRaises(HTTPException) as exc:
                await RecognitionService.get_review("rev-1", user)

        # exc.exception holds the actual error object in unittest
        self.assertEqual(exc.exception.status_code, 403)
        self.assertEqual(exc.exception.detail, "Access denied")

    async def test_review_not_found_raises_404(self):
        user = make_user(roles=["EMPLOYEE"])

        with patch.object(service.db.reviews, "find_unique", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as exc:
                await RecognitionService.get_review("ghost-id", user)

        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "Review not found")

# This allows you to run the file directly
if __name__ == '__main__':
    unittest.main()