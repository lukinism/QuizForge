from app.modules.attempts.models import Attempt, AttemptStatus
from app.modules.groups.models import Group
from app.modules.tests.models import Test, TestStatus, TestVisibility
from app.modules.users.models import User


async def get_admin_dashboard_stats() -> dict:
    return {
        "users_count": await User.find_all().count(),
        "tests_count": await Test.find_all().count(),
        "published_tests_count": await Test.find(Test.status == TestStatus.published).count(),
        "attempts_count": await Attempt.find_all().count(),
        "groups_count": await Group.find_all().count(),
    }


async def get_examiner_dashboard_stats(user: User) -> dict:
    tests_count = await Test.find(Test.author_id == user.id).count()
    test_ids = [test.id for test in await Test.find(Test.author_id == user.id).to_list()]
    attempts_count = await Attempt.find({"test_id": {"$in": test_ids}}).count() if test_ids else 0
    pending_review_count = await Attempt.find(
        {"test_id": {"$in": test_ids}, "status": AttemptStatus.pending_review},
    ).count() if test_ids else 0
    return {
        "tests_count": tests_count,
        "published_tests_count": await Test.find(Test.author_id == user.id, Test.status == TestStatus.published).count(),
        "attempts_count": attempts_count,
        "pending_review_count": pending_review_count,
        "groups_count": await Group.find(Group.created_by == user.id).count(),
    }


async def get_student_dashboard_stats(user: User) -> dict:
    return {
        "public_tests_count": await Test.find(
            Test.status == TestStatus.published,
            Test.visibility == TestVisibility.public,
        ).count(),
        "my_attempts_count": await Attempt.find(Attempt.user_id == user.id).count(),
        "completed_attempts_count": await Attempt.find(
            Attempt.user_id == user.id,
            Attempt.status == AttemptStatus.finished,
        ).count(),
    }
