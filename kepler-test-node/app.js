const http = require('http');

const server = http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/plain' });
  res.end('Hello from Node.js!');
});

const PORT = 8080;
server.listen(PORT, '0.0.0.0', () => {
  console.log(`Node.js Idle Server is listening on port ${PORT}...`);
});