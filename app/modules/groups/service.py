from fastapi import HTTPException, status

from app.core.audit import log_action
from app.core.utils import parse_object_id, utcnow
from app.modules.groups.models import Group, GroupJoinEvent, GroupJoinLink
from app.modules.groups.schemas import GroupCreate
from app.modules.users.models import User, UserRole


def _can_manage_group(user: User, group: Group) -> bool:
    return user.role == UserRole.admin or group.created_by == user.id


async def _normalize_members(user: User, member_ids: list[str]) -> list[str]:
    normalized_ids = [parse_object_id(member_id) for member_id in member_ids if member_id]
    if user.role == UserRole.admin or not normalized_ids:
        return normalized_ids

    members = await User.find({"_id": {"$in": normalized_ids}}).to_list()
    admin_ids = {member.id for member in members if member.role == UserRole.admin}
    return [member_id for member_id in normalized_ids if member_id not in admin_ids]


async def list_groups(user: User) -> list[Group]:
    if user.role == UserRole.admin:
        return await Group.find_all().sort("-created_at").to_list()
    return await Group.find(Group.created_by == user.id).sort("-created_at").to_list()


async def create_group(user: User, payload: GroupCreate) -> Group:
    if user.role not in {UserRole.admin, UserRole.examiner}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    group = Group(
        title=payload.title.strip(),
        description=payload.description.strip(),
        created_by=user.id,
        members=await _normalize_members(user, payload.members),
    )
    await group.insert()
    await log_action(str(user.id), "create_group", "group", str(group.id), {"title": group.title})
    return group


async def get_group_for_management(group_id: str, user: User) -> Group:
    group = await Group.get(parse_object_id(group_id))
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена.")
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    return group


async def update_group(group: Group, user: User, payload: GroupCreate) -> Group:
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    group.title = payload.title.strip()
    group.description = payload.description.strip()
    blocked_members = set(group.blocked_members)
    group.members = [
        member_id
        for member_id in await _normalize_members(user, payload.members)
        if member_id not in blocked_members
    ]
    await group.save()
    await log_action(str(user.id), "update_group", "group", str(group.id), {"title": group.title})
    return group


async def create_group_join_link(group: Group, user: User) -> GroupJoinLink:
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    link = GroupJoinLink(group_id=group.id, created_by=user.id)
    await link.insert()
    await log_action(str(user.id), "create_group_join_link", "group", str(group.id), {"token": link.token})
    return link


async def revoke_group_join_link(group: Group, user: User, link_id: str) -> GroupJoinLink:
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    link = await GroupJoinLink.get(parse_object_id(link_id))
    if not link or link.group_id != group.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ссылка не найдена.")

    link.is_active = False
    link.revoked_at = utcnow()
    await link.save()
    await log_action(str(user.id), "revoke_group_join_link", "group", str(group.id), {"link_id": str(link.id)})
    return link


async def list_group_join_links(group: Group, user: User) -> list[GroupJoinLink]:
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    return await GroupJoinLink.find(GroupJoinLink.group_id == group.id).sort("-created_at").to_list()


async def list_group_join_events(group: Group, user: User) -> list[GroupJoinEvent]:
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    return await GroupJoinEvent.find(GroupJoinEvent.group_id == group.id).sort("-joined_at").to_list()


async def join_group_by_token(token: str, user: User) -> Group:
    if user.role != UserRole.student:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Вступать в группы могут только тестируемые.")

    link = await GroupJoinLink.find_one(GroupJoinLink.token == token)
    if not link or not link.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ссылка для вступления недоступна.")

    group = await Group.get(link.group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена.")
    if user.id in group.blocked_members:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Вы заблокированы в этой группе.")

    if user.id not in group.members:
        group.members.append(user.id)
        await group.save()
        event = GroupJoinEvent(group_id=group.id, link_id=link.id, user_id=user.id)
        await event.insert()
        await log_action(str(user.id), "join_group_by_link", "group", str(group.id), {"link_id": str(link.id)})

    return group


async def remove_group_member(group: Group, user: User, member_id: str) -> Group:
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    parsed_member_id = parse_object_id(member_id)
    group.members = [existing_id for existing_id in group.members if existing_id != parsed_member_id]
    await group.save()
    await log_action(str(user.id), "remove_group_member", "group", str(group.id), {"member_id": parsed_member_id})
    return group


async def block_group_member(group: Group, user: User, member_id: str) -> Group:
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    parsed_member_id = parse_object_id(member_id)
    group.members = [existing_id for existing_id in group.members if existing_id != parsed_member_id]
    if parsed_member_id not in group.blocked_members:
        group.blocked_members.append(parsed_member_id)
    await group.save()
    await log_action(str(user.id), "block_group_member", "group", str(group.id), {"member_id": parsed_member_id})
    return group


async def unblock_group_member(group: Group, user: User, member_id: str) -> Group:
    if not _can_manage_group(user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    parsed_member_id = parse_object_id(member_id)
    group.blocked_members = [existing_id for existing_id in group.blocked_members if existing_id != parsed_member_id]
    await group.save()
    await log_action(str(user.id), "unblock_group_member", "group", str(group.id), {"member_id": parsed_member_id})
    return group
