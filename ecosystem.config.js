const commonEnv = {
  PYTHONPATH: "/app",
  XDG_CACHE_HOME: "/app/.cache",
  PRISMA_HOME: "/app/.prisma",
  PRISMA_PY_BINARIES_PATH: "/app/prisma_binaries",
  PRISMA_BINARY_CACHE_DIR: "/app/.cache",
};

// Define your microservices and their specific variables
const pythonServices = [
  { name: "auth", port: 8001, delay: 10000 },
  { name: "employees", port: 8003, delay: 15000 },
  { name: "wallet", port: 8004, delay: 20000 },
  { name: "recognition", port: 8005, delay: 25000 },
  { name: "rewards", port: 8006, delay: 30000 },
  { name: "organization", port: 8007, delay: 35000 },
];

// Map over the array to generate the PM2 configuration objects
const apps = pythonServices.map((svc) => ({
  name: svc.name,
  script: "/app/venv/bin/gunicorn",
  args: `src.${svc.name}.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${svc.port} --workers 1 --timeout 120 --graceful-timeout 60 --worker-tmp-dir /tmp`,
  cwd: "/app",
  interpreter: "none",
  autorestart: true,
  watch: false,
  wait_ready: true,
  listen_timeout: 120000,
  kill_timeout: 5000,
  restart_delay: svc.delay,
  env: commonEnv,
}));

// Push the Nginx configuration to the array
apps.push({
  name: "nginx",
  script: "/usr/sbin/nginx",
  args: "-c /app/nginx.conf -g 'daemon off;'",
  interpreter: "none",
  autorestart: true,
  watch: false,
  kill_timeout: 5000,
});

module.exports = { apps };