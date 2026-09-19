from datetime import date
from pydantic import BaseModel, ConfigDict, field_validator
from validation.profile import validate_name, validate_gender, validate_birth_date

class ProfileCreateSchema(BaseModel):
    first_name: str
    last_name: str
    gender: str
    date_of_birth: date
    info: str

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_names(cls, value: str):
        return validate_name(value)

    @field_validator("gender")
    @classmethod
    def validate_gender_field(cls, value: str):
        return validate_gender(value)

    @field_validator("date_of_birth")
    @classmethod
    def validate_age(cls, value: date):
        return validate_birth_date(value)

    @field_validator("info")
    @classmethod
    def validate_info(cls, value: str):
        if not value or not value.strip():
            raise ValueError("Info cannot be empty or consist only of spaces.")
        return value

class ProfileResponseSchema(BaseModel):
    id: int
    user_id: int
    first_name: str
    last_name: str
    gender: str
    date_of_birth: date
    info: str
    avatar: str

    model_config = ConfigDict(from_attributes=True)
