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