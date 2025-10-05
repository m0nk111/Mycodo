# coding=utf-8
import secrets
import uuid
from typing import Any, Optional, TypeVar

from flask import current_app

from mycodo.mycodo_flask.extensions import db

T = TypeVar('T', bound='CRUDMixin')


class CRUDMixin(object):
    """
    Basic Create, Read, Update and Delete methods
    Models that inherit from this class automatically get these CRUD methods
    """

    def save(self: T) -> Optional[T]:
        """creates the model in the database"""
        try:
            db.session.add(self)
            db.session.commit()
            return self
        except Exception as error:
            db.session.rollback()
            current_app.logger.error("Failed to save {model} due to error: {err}".format(model=self, err=error))
            return None

    def delete(self) -> None:
        """deletes the record from the database"""
        try:
            db.session.delete(self)
            db.session.commit()
        except Exception as error:
            current_app.logger.error("Failed to delete '{record}': '{err}'".format(record=self, err=error))


def set_api_key(length: int) -> bytes:
    """Generates an API key of specific length."""
    return secrets.token_bytes(length)


def set_uuid() -> str:
    """returns a uuid string."""
    return str(uuid.uuid4())


def clone_model(model: Any, **kwargs: Any) -> Optional[Any]:
    """Clone an arbitrary sqlalchemy model object without its primary key values."""
    # Ensure the model’s data is loaded before copying.
    try:
        model.id
    except Exception:
        return None

    table = model.__table__
    non_pk_columns = [k for k in table.columns.keys() if k not in table.primary_key]
    data = {c: getattr(model, c) for c in non_pk_columns}
    data.update(kwargs)

    clone = model.__class__(**data)
    db.session.add(clone)
    db.session.commit()
    return clone
