# Proof Viewer

A static HTML/JS viewer for proof session logs.

## Setup

1. Ensure proof logs are generated in `proofs/` directory
2. Start a simple HTTP server from the **project root** (not from the viewer directory):

```bash
# From the project root (c:\dev\Prover)
# Python 3
python -m http.server 8000

# Or Node.js
npx http-server -p 8000
```

3. Open `http://localhost:8000/viewer/index.html` in your browser

**Important**: The server must be run from the project root directory, not from the `viewer/` subdirectory, so that the viewer can access the `proofs/` directory.

## Features

- View proof sessions with structured event display
- Navigate between proofs with Previous/Next buttons
- Hide internal tool call requests (only shows results)
- Automatically discovers proofs from `proofs` directory
- Sorts proofs by timestamp (newest first)

