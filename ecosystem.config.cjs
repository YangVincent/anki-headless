const path = require('path');

module.exports = {
  apps: [{
    name: 'anki-bot',
    cwd: __dirname,
    script: path.join(__dirname, '.venv', 'bin', 'python3'),
    args: path.join(__dirname, 'bot.py'),
    interpreter: 'none',
    autorestart: true,
  }]
};
