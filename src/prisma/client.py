from prisma import Prisma
import contextvars

_db_var: contextvars.ContextVar = contextvars.ContextVar('db')

def get_db() -> Prisma:
    try:
        return _db_var.get()
    except LookupError:
        db = Prisma()
        _db_var.set(db)
        return db

db = Prisma()