from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.core.dependencies import require_roles
from app.core.templates import templates
from app.modules.groups.service import (
    block_group_member,
    create_group,
    create_group_join_link,
    get_group_for_management,
    join_group_by_token,
    list_group_join_events,
    list_group_join_links,
    list_groups,
    remove_group_member,
    revoke_group_join_link,
    unblock_group_member,
    update_group,
)
from app.modules.groups.schemas import GroupCreate
from app.modules.tests.models import Test, TestAssignment, TestStatus
from app.modules.tests.service import create_test_assignment, list_manageable_tests
from app.modules.users.models import User, UserRole
from app.modules.users.service import list_users


router = APIRouter(prefix="/groups", tags=["groups"])


def _group_template(current_user: User) -> str:
    return "admin/groups.html" if current_user.role == UserRole.admin else "examiner/groups.html"


async def _group_candidate_users(current_user: User) -> list[User]:
    users = await list_users()
    if current_user.role == UserRole.admin:
        return users
    return [user for user in users if user.role != UserRole.admin]


async def _groups_context(request: Request, current_user: User, editing_group=None) -> dict:
    groups = await list_groups(current_user)
    all_users = await _group_candidate_users(current_user)
    users_by_id = {str(user.id): user for user in all_users}
    invite_links = {}
    join_events = {}

    for group in groups:
        invite_links[str(group.id)] = await list_group_join_links(group, current_user)
        join_events[str(group.id)] = await list_group_join_events(group, current_user)

    return {
        "current_user": current_user,
        "groups": groups,
        "tests": await list_manageable_tests(current_user),
        "all_users": all_users,
        "users_by_id": users_by_id,
        "editing_group": editing_group,
        "invite_links": invite_links,
        "join_events": join_events,
        "base_url": str(request.base_url),
    }


async def _group_form_context(current_user: User, group=None) -> dict:
    return {
        "current_user": current_user,
        "group": group,
        "all_users": await _group_candidate_users(current_user),
    }


async def _group_detail_context(request: Request, current_user: User, group) -> dict:
    all_users = await _group_candidate_users(current_user)
    users_by_id = {str(user.id): user for user in all_users}
    tests = await list_manageable_tests(current_user)
    assignments = await TestAssignment.find(TestAssignment.group_id == group.id).sort("-created_at").to_list()
    assignment_tests = await Test.find({"_id": {"$in": [assignment.test_id for assignment in assignments]}}).to_list() if assignments else []
    return {
        "current_user": current_user,
        "group": group,
        "tests": tests,
        "published_tests": [test for test in tests if test.status == TestStatus.published],
        "all_users": all_users,
        "users_by_id": users_by_id,
        "invite_links": await list_group_join_links(group, current_user),
        "join_events": await list_group_join_events(group, current_user),
        "assignments": assignments,
        "assignment_tests_by_id": {test.id: test for test in assignment_tests},
        "base_url": str(request.base_url),
    }


@router.get("")
async def groups_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    return templates.TemplateResponse(
        request=request,
        name=_group_template(current_user),
        context={
            "current_user": current_user,
            "groups": await list_groups(current_user),
        },
    )


@router.get("/create")
async def create_group_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    return templates.TemplateResponse(
        request=request,
        name="examiner/group_form.html",
        context=await _group_form_context(current_user),
    )


@router.post("")
async def create_group_submit(
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    title: str = Form(...),
    description: str = Form(""),
    members: list[str] = Form(default=[]),
):
    payload = GroupCreate(title=title, description=description, members=members)
    group = await create_group(current_user, payload)
    return RedirectResponse(url=f"/groups/{group.id}", status_code=303)


@router.get("/join/{token}")
async def join_group_page(
    token: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    group = await join_group_by_token(token, current_user)
    return templates.TemplateResponse(
        request=request,
        name="student/group_joined.html",
        context={"current_user": current_user, "group": group},
    )


@router.get("/{group_id}/edit")
async def edit_group_page(
    group_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    editing_group = await get_group_for_management(group_id, current_user)
    return templates.TemplateResponse(
        request=request,
        name="examiner/group_form.html",
        context=await _group_form_context(current_user, group=editing_group),
    )


@router.post("/{group_id}")
async def update_group_submit(
    group_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    title: str = Form(...),
    description: str = Form(""),
    members: list[str] = Form(default=[]),
):
    group = await get_group_for_management(group_id, current_user)
    payload = GroupCreate(title=title, description=description, members=members)
    await update_group(group, current_user, payload)
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)


@router.get("/{group_id}")
async def group_detail_page(
    group_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    group = await get_group_for_management(group_id, current_user)
    return templates.TemplateResponse(
        request=request,
        name="examiner/group_detail.html",
        context=await _group_detail_context(request, current_user, group),
    )


@router.post("/{group_id}/assignments")
async def create_group_assignment_submit(
    group_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    test_id: str = Form(...),
):
    group = await get_group_for_management(group_id, current_user)
    test = await Test.get(test_id)
    if not test:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тест не найден.")
    assignment = await create_test_assignment(test, current_user, group.id)
    return RedirectResponse(url=f"/tests/assignments/{assignment.id}/monitor", status_code=303)


@router.post("/{group_id}/links")
async def create_group_link_submit(
    group_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    group = await get_group_for_management(group_id, current_user)
    await create_group_join_link(group, current_user)
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)


@router.post("/{group_id}/links/{link_id}/revoke")
async def revoke_group_link_submit(
    group_id: str,
    link_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    group = await get_group_for_management(group_id, current_user)
    await revoke_group_join_link(group, current_user, link_id)
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)


@router.post("/{group_id}/members/{member_id}/remove")
async def remove_group_member_submit(
    group_id: str,
    member_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    group = await get_group_for_management(group_id, current_user)
    await remove_group_member(group, current_user, member_id)
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)


@router.post("/{group_id}/members/{member_id}/block")
async def block_group_member_submit(
    group_id: str,
    member_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    group = await get_group_for_management(group_id, current_user)
    await block_group_member(group, current_user, member_id)
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)


@router.post("/{group_id}/members/{member_id}/unblock")
async def unblock_group_member_submit(
    group_id: str,
    member_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    group = await get_group_for_management(group_id, current_user)
    await unblock_group_member(group, current_user, member_id)
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)
