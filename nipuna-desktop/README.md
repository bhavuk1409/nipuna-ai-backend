# Nipuna Desktop Agent

UI app that runs the Tally MCP server locally and connects to the Nipuna backend.

## Run locally

```bash
npm install
npm start
```

## Build Windows installer

```bash
npm run build:win
```

## Build macOS installer

```bash
npm run build:mac
```

## Sign-in flow

The agent opens the browser to the web app at:

```
http://localhost:5173/desktop-auth?redirect_uri=http://localhost:41731/callback
```

After sign-in, the web app should redirect to the callback URL with a token:

```
http://localhost:41731/callback?token=CLERK_JWT
```

The agent captures the token and connects to:

```
ws://localhost:8000/api/v1/ws/agents
```
