const commonEnv = {
  PYTHONPATH: "/app",
  XDG_CACHE_HOME: "/app/.cache",
  PRISMA_HOME: "/app/.prisma",
  PRISMA_PY_BINARIES_PATH: "/app/prisma_binaries",
  PRISMA_BINARY_CACHE_DIR: "/app/.cache",
};

// Define your microservices and their specific initial startup delay (in seconds)
const pythonServices = [
  { name: "auth",         port: 8001, delay: 5 },
  { name: "roles",        port: 8002, delay: 10 },
  { name: "employees",    port: 8003, delay: 15 },
  { name: "wallet",       port: 8004, delay: 20 },
  { name: "recognition",  port: 8005, delay: 25 },
  { name: "rewards",      port: 8006, delay: 30 },
  { name: "organization", port: 8007, delay: 35 },
];

// 1. Start Nginx FIRST so the gateway is up immediately
const apps = [
  {
    name: "nginx",
    script: "/usr/sbin/nginx",
    args: "-c /app/nginx.conf -g 'daemon off;'",
    interpreter: "none",
    autorestart: true,
    watch: false,
    kill_timeout: 5000,
  }
];

// 2. Map over the array to generate the staggered PM2 configurations
const pythonApps = pythonServices.map((svc) => ({
  name: svc.name,
  script: "bash",
  // TRICK: Use bash 'sleep' to stagger initial boot, then 'exec' to hand the PID to Gunicorn
  args: `-c 'sleep ${svc.delay} && exec /app/venv/bin/gunicorn src.${svc.name}.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${svc.port} --workers 1 --timeout 120 --graceful-timeout 60 --worker-tmp-dir /tmp'`,
  cwd: "/app",
  interpreter: "none",
  autorestart: true,
  watch: false,
  wait_ready: false,      // <-- CRITICAL: Do NOT wait for Node IPC signals
  min_uptime: 5000,       // Consider it "online" if it survives for 5 seconds
  kill_timeout: 5000,
  restart_delay: 5000,    // If the app crashes, wait 5 seconds before restarting
  env: commonEnv,
}));

// Push all Python services into the array after Nginx
apps.push(...pythonApps);

module.exports = { apps };