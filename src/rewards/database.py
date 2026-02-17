from prisma import Prisma

# Initialize the Prisma client
prisma_client = Prisma()

async def connect_db():
    """Connect to the Prisma database."""
    if not prisma_client.is_connected():
        await prisma_client.connect()

async def disconnect_db():
    """Disconnect from the Prisma database."""
    if prisma_client.is_connected():
        await prisma_client.disconnect()

async def get_db():
    """Dependency to yield the Prisma client for our FastAPI routes."""
    if not prisma_client.is_connected():
        await prisma_client.connect()
    yield prisma_client