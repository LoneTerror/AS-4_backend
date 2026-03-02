from prisma import Prisma

db = Prisma(auto_register=True)

def get_db() -> Prisma:
    return db