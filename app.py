"""CV serving Flask app"""
import base64
import json
import uuid
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import RLock
from types import ModuleType
from typing import (
    TypedDict,
    Optional,
    MutableMapping,
    Iterator,
    Set,
    Any,
    Mapping,
    Collection,
)

import dataset
import pytimeparse
from flask import Flask, Request, Response, render_template, abort, request
from flask_httpauth import HTTPBasicAuth
from sqlalchemy import Integer, UnicodeText, Boolean, DateTime, Column
from werkzeug.local import LocalProxy
from werkzeug.security import check_password_hash


USERS_TABLE_NAME: str = "users"
TOKEN_TABLE_NAME: str = "tokens"
CONNECTIONS_TABLE_NAME: str = "connections"


app: Flask = Flask(__name__)
auth: HTTPBasicAuth = HTTPBasicAuth()
database: dataset.Database = dataset.connect(
    url="sqlite:///app.db.sqlite",
    engine_kwargs=dict(connect_args=dict(check_same_thread=False)),
)
db_thread_lock: RLock = RLock()


# TODO: Should have used SQLAlchemy models, but idk
@auth.verify_password
def verify_password(username: str, password: str):
    with db_context() as db:
        users_table: dataset.Table = db[USERS_TABLE_NAME]
        user_db: Optional[MutableMapping] = users_table.find_one(username=username)
    if user_db is not None:
        user: User = User(**user_db)
        if check_password_hash(user["password"], password):
            return user
    return None


class User(TypedDict):
    """TypedDict class for users stored in database"""

    username: str
    password: str
    is_admin: bool


class Token(TypedDict):
    """TypedDict class for tokens stored in database"""

    id: str
    name: str
    active: bool
    expiry: datetime


class LoggedConnection(TypedDict, total=False):
    """TypedDict class for logged connections stored in database"""

    id: int
    request_time: datetime
    token_id: str
    token_valid: bool
    client_ip: str
    request_data: str


# noinspection PyProtectedMember
# pylint: disable=protected-access
def ensure_db_schema() -> None:
    """
    Ensures the database schema exists, creating it if it doesn't.
    """
    database.query("PRAGMA journal_mode = WAL").close()
    users_table: dataset.Table = database.create_table(
        USERS_TABLE_NAME, primary_id=False
    )
    users_table._sync_table(
        [
            Column("username", UnicodeText, nullable=False, primary_key=True),
            Column("password", UnicodeText, nullable=False),
            Column("is_admin", Boolean, nullable=False),
        ]
    )
    tokens_table: dataset.Table = database.create_table(
        TOKEN_TABLE_NAME, primary_id=False
    )
    tokens_table._sync_table(
        [
            Column("id", UnicodeText, nullable=False, primary_key=True),
            Column("name", UnicodeText, nullable=False),
            Column("active", Boolean, nullable=False),
            Column("expiry", DateTime, nullable=False),
        ]
    )
    connections_table: dataset.Table = database.create_table(
        CONNECTIONS_TABLE_NAME, primary_id=False
    )
    connections_table._sync_table(
        [
            Column("id", Integer, nullable=False, autoincrement=True, primary_key=True),
            Column("request_time", DateTime, nullable=False),
            Column("token_id", UnicodeText, nullable=False),
            Column("token_valid", Boolean, nullable=False),
            Column("client_ip", UnicodeText, nullable=False),
            Column("request_data", UnicodeText, nullable=False),
        ]
    )


@contextmanager
def db_context() -> Iterator[dataset.Database]:
    """
    Context manager function that wraps a database connection and transaction
    ensuring also that only a single thread is using the database at one time.
    :return: the `dataset.Database` object
    """
    with db_thread_lock:
        try:
            with database:
                yield database
        except Exception as exc:
            app.logger.warning(f"Error while in db transaction, rolled back:\n{exc}")
            raise


def validate_token(token_id: str) -> bool:
    with db_context() as db:
        tokens_table: dataset.Table = db[TOKEN_TABLE_NAME]
        token_db: Optional[MutableMapping] = tokens_table.find_one(id=token_id)
    if token_db is None:
        return False
    token: Token = Token(**token_db)
    if not token["active"] or datetime.now() > token["expiry"]:
        return False
    return True


@app.route("/create_token/<string:token_name>")
@auth.login_required
def create_token(token_name: str):
    user: User = auth.current_user()
    if not user["is_admin"]:
        abort(403)
    expiry_arg: Optional[str] = request.args.get("expiry")
    token_expiry_delta: timedelta
    if expiry_arg is not None:
        expiry_seconds: int = pytimeparse.parse(expiry_arg)
        token_expiry_delta = timedelta(seconds=expiry_seconds)
    else:
        token_expiry_delta = timedelta(days=60)
    token_expiry: datetime = datetime.now() + token_expiry_delta
    token_id: str = base64.b64encode(
        zlib.adler32(uuid.uuid4().bytes).to_bytes(4, "little")
    ).decode()[:6]
    token: Token = Token(id=token_id, name=token_name, active=True, expiry=token_expiry)
    with db_context() as db:
        tokens_table: dataset.Table = db[TOKEN_TABLE_NAME]
        tokens_table.insert(token)
    return f"OK! New token id = {token_id}"


def flatten(obj: Any, pending_ids: Optional[Set[int]] = None) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (int, bool, float, str)):
        return obj
    if isinstance(obj, bytes):
        return obj.decode()
    if isinstance(obj, LocalProxy):
        # noinspection PyProtectedMember
        # pylint: disable=protected-access
        obj = obj._get_current_object()
    if pending_ids is None:
        pending_ids = set()
    obj_id: int = id(obj)
    if obj_id in pending_ids:
        return f"[recursion! id={obj_id}]"
    pending_ids.add(obj_id)
    result: Any
    if isinstance(obj, Mapping):
        result = {k: flatten(v, pending_ids=pending_ids) for k, v in obj.items()}
    elif isinstance(obj, Collection) and hasattr(obj, "__iter__"):
        result = [flatten(o, pending_ids=pending_ids) for o in obj]
    elif isinstance(obj, object):
        result = {
            n: flatten(v, pending_ids=pending_ids)
            for n in dir(obj)
            if not n.startswith("_")
            and not callable(v := getattr(obj, n, None))
            and not isinstance(v, (type, ModuleType))
        }
    else:
        result = repr(obj)
    pending_ids.discard(obj_id)
    return result


def log_request(req: Request, token_id: str, token_valid: Optional[bool] = None):
    if token_valid is None:
        token_valid = validate_token(token_id)

    req_time: datetime = datetime.now()
    req_flat: Any = flatten(req)
    req_data: str = json.dumps(req_flat)
    connection: LoggedConnection = LoggedConnection(
        request_time=req_time,
        token_id=token_id,
        token_valid=token_valid,
        client_ip=req.remote_addr,
        request_data=req_data,
    )
    with db_context() as db:
        connections_table: dataset.Table = db[CONNECTIONS_TABLE_NAME]
        connections_table.insert(connection)


@app.route("/cv/<string:token_id>")
def cv(token_id: str) -> Response:
    token_valid: bool = validate_token(token_id=token_id)
    log_request(request, token_id=token_id, token_valid=token_valid)
    if token_valid:
        return render_template("cv.html")
    abort(404)


app.before_first_request(ensure_db_schema)


if __name__ == "__main__":
    app.run(debug=True)
