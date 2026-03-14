const commonEnv = {
  PYTHONPATH: "/app",
  // Match the path in the Dockerfile
  PRISMA_BINARY_CACHE_DIR: "/app/.cache/prisma-python", 
  XDG_CACHE_HOME: "/app/.cache",
  PRISMA_HOME: "/app/.prisma",
  FORCE_COLOR: "1" 
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
  { name: "analytics",    port: 8008, delay: 40 }
];

// 1. Start Nginx FIRST so the gateway is up immediately
const apps = [
  {
    name: "nginx",
    script: "nginx",
    // Ensure Nginx uses the config and stays in foreground for PM2
    args: "-c /app/nginx.conf -g 'daemon off;'",
    interpreter: "none",
    autorestart: true,
    out_file: "/dev/null",   
    error_file: "/dev/null"  
  }
];

const pythonApps = pythonServices.map((svc) => ({
  name: svc.name,
  script: "bash",
  // Using 'python -m gunicorn' is safer for finding modules like 'uvicorn'
  args: `-c 'sleep ${svc.delay} && exec /app/venv/bin/python -m gunicorn src.${svc.name}.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${svc.port} --workers 1 --timeout 120'`,
  cwd: "/app",
  interpreter: "none",
  autorestart: true,
  env: commonEnv, // Apply the cache paths here
  out_file: "/dev/null",   
  error_file: "/dev/null", 
}));

apps.push(...pythonApps);
module.exports = { apps };