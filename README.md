# Employee Recognition & Rewards Platform (Backend)

## 📋 **Project Overview**
This is the backend service for the **Employee Recognition & Rewards Platform**, a system designed to boost organizational engagement through peer-to-peer recognition, automated celebrations, and measurable impact analytics.

The platform enables employees to send points-based appreciation, redeem rewards from a catalog, and integrates seamlessly with workplace tools like Slack and Microsoft Teams.

## 🛠 **Tech Stack**

### **Core Application**
**Framework:** FastAPI (Python 3.10+)
**ORM:** Prisma Client Python (Database Access)
**Database:** PostgreSQL (Transactional Data) 
**Caching & Rate Limiting:** Redis 
**Authentication:** OAuth2 / OIDC (Keycloak or Internal Auth)

### **Infrastructure & DevOps**
**Containerization:** Docker & Kubernetes (Helm) [cite: 53]
**Infrastructure as Code:** Terraform (AWS/Azure/GCP agnostic) [cite: 54]
**Background Workers:** Celery + RabbitMQ (for notifications/async tasks) [cite: 50]
**Storage:** AWS S3 (for image/video attachments) [cite: 51]
**CI/CD:** GitHub Actions [cite: 55]

## ✨ **Key Features**
1. **Recognition Engine:** Peer-to-peer recognition with point values, hashtags (e.g., #collaboration), and rich media attachments.
2. **Rewards Catalog:** Inventory management for gift cards, swag, and redemption workflows.
3. **Automations:** Scheduled milestone celebrations (birthdays, work anniversaries).
4. **Integrations:** Webhooks and APIs for Slack/Teams bots and HRIS synchronization.
5.  **Analytics:** Manager dashboards for tracking participation trends and budget usage.

## 🚀 **Getting Started**

### Prerequisites
* Python 3.10+
* Node.js (Required for Prisma CLI)
* Docker & Docker Compose (for local DB/Redis)

### 1. Environment Configuration
Create a `.env` file in the root directory:

# Application

```
PROJECT_NAME="Employee R&R API"
DEBUG=True
SECRET_KEY=change_this_secret_key
```

# Database (Prisma)

## 1. Add DATABASE_URL to .env

```
DATABASE_URL="postgresql://user:password@localhost:5432/rr_db?schema=public"
```

## Now initialize the prisma

```
prisma init
```

## 2. Pull schema from DB

```
prisma db pull
```

## 3. Generate Prisma client

```
prisma generate
```

## 4. Start backend

```
uvicorn main:app --reload
```

## Caching (Optional)

```
REDIS_URL="redis://localhost:6379/0"
```

## External Services

```
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
S3_BUCKET_NAME=rr-attachments
```

# 🛠️ Setup & Installation


## **1. Clone the repository**

```
git clone https://github.com/LoneTerror/AS-4_backend.git
cd AS-4_backend
```

## **2. Create a virtual environment folder (venv)**

```
python -m venv venv
```

## **3. Activate the virtual environment**

```
.\venv\Scripts\activate
```

## **4. Install Dependencies using the following `pip` command (only after activating the venv)**

```
pip install -r requirements.txt
```

## **5. Initialize Prisma**

```
prisma init
```

## **6. Pull the schema from Database using Prisma**

```
prisma db pull
```

## **7. Generate the Prisma**

```
prisma generate
```

## **8. To work with microservices, switch to `/src`**

```
cd src
```

## **Set the database `.env` file at root folder**

```
DATABASE_URL="postgresql://user:pass@ep-cool-pooler.region.neon.tech/neondb?sslmode=require"
```

## **Uvicorn Commands**

```
uvicorn src.main:app
```

## Git Initialization Commands
* Now, open your terminal in the project folder and run these commands one by one to push everything to GitHub.

**Step 1: Initialize Git**

```
git init
```

# ***OR***
*(Cloning is recommend if you want to contribute and suggest changes to this repository)*

**Clone this repository**

```
git clone https://github.com/LoneTerror/AS-4_backend.git
```

**Step 2: Link to GitHub Repository (if you have ran the `git init` command)**

```
git remote add origin https://github.com/LoneTerror/AS-4_backend.git
```

**Step 3: Pull Recent Changes Before Pushing**

```
git pull
```

**Step 4: Create New Branch before push**

```
git branch -M <git_username>-patch-<patch_number>
```
*(Example: git branch -M loneTerror-patch-0)*

**Step 5: Add Files**

```
git add .
```

**Step 6: Commit**

```
git commit -m "Initial commit: Backend Configuration Done"
```

**Step 7: Push (on the new branch you created earlier)**

```
git git push -u origin <branchname>
```
*(Example: git push -u origin loneTerror-patch-0)*

**Step 8: Pull Request**

* Go To  [Pull Requests](https://github.com/LoneTerror/AS-4_backend.git)
* The CodeOwners will review your pull request, then they will approve/reject
* If your pull request is approved, then your created branch will be merged and deleted