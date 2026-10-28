// pm2 process definition. Start with: pm2 start ecosystem.config.cjs && pm2 save
module.exports = {
  apps: [
    {
      name: 'iot-api',
      script: 'src/server.js',
      cwd: '/opt/IoT-api',
      // Config comes from .env (mode 600, owned by iotapi).
      node_args: '--env-file=/opt/IoT-api/.env',
      // pm2 runs as root here; drop privileges so the API doesn't.
      uid: 'iotapi',
      gid: 'iotapi',
      autorestart: true,
      max_memory_restart: '400M',
      kill_timeout: 5000,
    },
  ],
};
