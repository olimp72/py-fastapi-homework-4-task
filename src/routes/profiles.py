from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from datetime import date
from pydantic import ValidationError

from config import get_jwt_auth_manager, get_s3_storage_client
from database import get_db
from security.http import get_token
from security.interfaces import JWTAuthManagerInterface
from storages.interfaces import S3StorageInterface
from exceptions import BaseSecurityError

from database.models.accounts import UserModel, UserProfileModel, UserGroupEnum, GenderEnum
from schemas.profiles import ProfileResponseSchema, ProfileCreateSchema
from validation.profile import validate_image

router = APIRouter(prefix="/users", tags=["Profiles"])


@router.post(
    "/{user_id}/profile/",
    response_model=ProfileResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create User Profile",
    description="Creates a new profile for a user and uploads the avatar to MinIO storage."
)
async def create_user_profile(
        user_id: int,
        first_name: str = Form(...),
        last_name: str = Form(...),
        gender: str = Form(...),
        date_of_birth: date = Form(...),
        info: str = Form(...),
        avatar: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        token: str = Depends(get_token),
        auth_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
        s3_client: S3StorageInterface = Depends(get_s3_storage_client)
):
    try:
        payload = auth_manager.decode_access_token(token)
        token_user_id = payload.get("user_id")
    except BaseSecurityError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired."
        )

    token_user_result = await db.execute(
        select(UserModel)
        .options(joinedload(UserModel.group))
        .where(UserModel.id == token_user_id)
    )
    token_user = token_user_result.scalars().first()

    is_admin = token_user and token_user.group and token_user.group.name == UserGroupEnum.ADMIN

    if token_user_id != user_id and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit this profile."
        )

    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalars().first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active."
        )

    profile_result = await db.execute(select(UserProfileModel).where(UserProfileModel.user_id == user_id))
    existing_profile = profile_result.scalars().first()

    if existing_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has a profile."
        )

    try:
        ProfileCreateSchema(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=date_of_birth,
            info=info
        )
        validate_image(avatar)
    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        if "info" in str(e) and ("empty" in error_msg.lower() or "space" in error_msg.lower()):
            error_msg = "Info field cannot be empty or contain only spaces."
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )

    try:
        safe_filename = avatar.filename if avatar.filename else "avatar.jpg"
        file_extension = safe_filename.split(".")[-1]
        file_name = f"avatars/{user_id}_avatar.{file_extension}"

        avatar_content = await avatar.read()
        upload_result = await s3_client.upload_file(
            file_data=avatar_content,
            file_name=file_name
        )

        if isinstance(upload_result, str) and upload_result.startswith("http"):
            avatar_url = upload_result
        elif hasattr(s3_client, "get_file_url"):
            avatar_url = await s3_client.get_file_url(file_name)
        else:
            avatar_url = f"http://localhost:9000/theater-storage/{file_name}"

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload avatar. Please try again later."
        )

    new_profile = UserProfileModel(
        user_id=user_id,
        first_name=first_name.lower(),
        last_name=last_name.lower(),
        gender=GenderEnum(gender),
        date_of_birth=date_of_birth,
        info=info,
        avatar=file_name
    )

    db.add(new_profile)
    await db.commit()
    await db.refresh(new_profile)

    response_data = ProfileResponseSchema.model_validate(new_profile)
    response_data.avatar = avatar_url

    return response_data
