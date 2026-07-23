# ☁️ Cloud & GitHub Deployment Guide - Alpha Quant Platform

This guide provides step-by-step instructions for deploying `Alpha Quant Platform` to Git and Cloud VPS / Docker environments.

---

## 1. Push Code to GitHub Repository

```bash
git add .
git commit -m "feat: Add Real-Time Economic News Filter, HRP fixes, MT5 connection guards, and Docker cloud deployment"
git push origin main
```

---

## 2. Cloud VPS Deployment via Docker Compose (AWS / DigitalOcean / Hetzner)

### Step 1: Clone Repository on Cloud VPS
```bash
git clone <YOUR_GITHUB_REPO_URL>
cd Alpha-Quant-Trading-Bot
```

### Step 2: Configure Environment Variables
Copy and edit `.env`:
```bash
cp .env.example .env
nano .env
```
Ensure your `MT5_ACCOUNT_LOGIN`, `MT5_ACCOUNT_PASSWORD`, and `MT5_ACCOUNT_SERVER` are set correctly.

### Step 3: Launch Containers
```bash
docker-compose up -d --build
```

### Step 4: Verify Running Services
```bash
docker-compose ps
docker-compose logs -f alpha_quant_engine
```

---

## 3. Platform Verification Command
To run system integrity tests on the server:
```bash
docker exec -it alpha_quant_engine python -m alpha_platform.verify_platform
```
