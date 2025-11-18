const PROOFS_DIR = (() => {
    const path = window.location.pathname;
    if (path.includes('/viewer/')) {
        return '../proofs/';
    } else {
        return 'proofs/';
    }
})();

let proofs = [];
let currentIndex = 0;

async function loadProofs() {
    try {
        proofs = await discoverProofs();
        if (proofs.length === 0) {
            document.getElementById('proofContainer').innerHTML = 
                '<div class="loading">No proofs found. Run a proof session first.</div>';
            return;
        }
        
        currentIndex = 0;
        await loadProof(proofs[currentIndex]);
        updateNavigation();
    } catch (error) {
        console.error('Error loading proofs:', error);
        document.getElementById('proofContainer').innerHTML = 
            `<div class="loading">Error loading proofs: ${error.message}<br><br>Note: This viewer requires a web server to run. Use Python: <code>python -m http.server 8000</code> from the project root.</div>`;
    }
}

async function discoverProofs() {
    try {
        const response = await fetch(PROOFS_DIR);
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error(`Proofs directory not found at ${PROOFS_DIR}. Make sure the server is running from the project root directory.`);
            }
            throw new Error(`Failed to fetch directory listing: ${response.status} ${response.statusText}`);
        }
        
        const html = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        
        const links = doc.querySelectorAll('a');
        const proofIds = [];
        
        links.forEach(link => {
            const href = link.getAttribute('href');
            if (href && href.endsWith('.json')) {
                const sessionId = href.replace('.json', '');
                proofIds.push(sessionId);
            }
        });
        
        if (proofIds.length === 0) {
            return [];
        }
        
        const proofsWithTimestamps = await Promise.all(
            proofIds.map(async (id) => {
                try {
                    const proofResponse = await fetch(`${PROOFS_DIR}${id}.json`);
                    if (proofResponse.ok) {
                        const proof = await proofResponse.json();
                        return {
                            id,
                            timestamp: proof.timestamp || proof.metadata?.timestamp || '0'
                        };
                    }
                } catch (e) {
                    console.warn(`Failed to load proof ${id}:`, e);
                }
                return { id, timestamp: '0' };
            })
        );
        
        proofsWithTimestamps.sort((a, b) => {
            return new Date(b.timestamp) - new Date(a.timestamp);
        });
        
        return proofsWithTimestamps.map(p => p.id);
    } catch (error) {
        console.error('Error discovering proofs:', error);
        return [];
    }
}

function createStepObjects(events) {
    const steps = [];
    let currentStepIndex = -1;
    for (const event of events) {
        if (event.type === 'model_output') {
            steps.push({
                type: 'model_output',
                content: event.content || {},
                toolResults: {}
            });
            currentStepIndex = steps.length - 1;
        } else if (event.type === 'tool_result' && currentStepIndex >= 0) {
            const toolCallId = event.tool_call_id;
            const toolCalls = steps[currentStepIndex].content.tool_calls || [];
            const matchingCall = toolCalls.find(tc => tc.id === toolCallId);
            if (matchingCall) {
                steps[currentStepIndex].toolResults[toolCallId] = event;
            } else {
                // Fallback: unmatched
                if (!steps[currentStepIndex].unmatchedTools) steps[currentStepIndex].unmatchedTools = [];
                steps[currentStepIndex].unmatchedTools.push(event);
            }
        }
        // Skip other types
    }
    // Merge accumulating fields to final step
    if (steps.length > 0) {
        const finalContent = steps[steps.length - 1].content;
        for (let i = 0; i < steps.length - 1; i++) {
            const step = steps[i];
            if (step.content.evidence) finalContent.evidence = [...(finalContent.evidence || []), ...step.content.evidence];
            if (step.content.derivation) finalContent.derivation = [...(finalContent.derivation || []), ...step.content.derivation];
        }
    }
    return steps;
}

window.codeStore = window.codeStore || {};
window.queryStore = window.queryStore || {};

function copyCodeById(codeId) {
    const code = window.codeStore[codeId];
    if (!code) {
        const codeElement = document.getElementById(codeId);
        if (codeElement) {
            window.codeStore[codeId] = codeElement.textContent;
            return copyCodeById(codeId);
        }
        return;
    }
    
    const codeElement = document.getElementById(codeId);
    const button = codeElement?.closest('.code-wrapper')?.querySelector('.copy-code-btn');
    
    navigator.clipboard.writeText(code).then(() => {
        if (button) {
            const originalText = button.textContent;
            button.textContent = 'Copied!';
            button.classList.add('copied');
            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove('copied');
            }, 2000);
        }
    }).catch(err => {
        console.error('Copy failed:', err);
        alert('Failed to copy code');
    });
}

function renderStep(step, index, totalSteps) {
    let html = `<details class="step-collapsible" data-step-index="${index}">
        <summary class="step-header">${escapeHtml(step.content.current_step || `Step ${index + 1}`)}</summary>
        <div class="step-body">`;

    if (step.content.assumptions && step.content.assumptions.length > 0) {
        html += `<div class="assumptions-section">
            <h4>Assumptions</h4>
            <ul>${step.content.assumptions.map(ass => `<li>${escapeHtml(ass)}</li>`).join('')}</ul>
        </div>`;
    }

    const toolCalls = step.content.tool_calls || [];
    if (toolCalls.length > 0) {
        html += `<div class="tool-calls-section"><h4>Tool Calls</h4>`;
        toolCalls.forEach(tc => {
            const id = tc.id;
            const toolResult = step.toolResults[id];
            let argsObj = {};
            try {
                argsObj = typeof tc.function.arguments === 'string' 
                    ? JSON.parse(tc.function.arguments) 
                    : tc.function.arguments;
            } catch (e) {
                console.warn('Failed to parse tool arguments:', e);
            }
            html += `<div class="tool-card">
                <h5>${tc.function.name} (${id})</h5>`;
            if (toolResult) {
                if (tc.function.name === 'python_execute') {
                    const code = argsObj.code || '';
                    const highlightedCode = Prism.highlight(code, Prism.languages.python, 'python');
                    const codeId = `code-${id}`;
                    window.codeStore[codeId] = code;
                    html += `<div class="code-wrapper">
                        <div class="code-input">
                            <button class="copy-code-btn" onclick="copyCodeById('${codeId}')" aria-label="Copy code">Copy</button>
                            <pre><code class="language-python" id="${codeId}">${highlightedCode}</code></pre>
                        </div>
                        <div class="output-label">Output:</div>
                        <div class="code-output">${escapeHtml(toolResult.result.output || '')}</div>
                    </div>`;
                } else if (tc.function.name === 'web_search') {
                    const query = argsObj.query || '';
                    const content = toolResult.result.content || '';
                    const markdownHtml = marked.parse(content);
                    const queryId = `query-${id}`;
                    window.queryStore[queryId] = query;
                    
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = markdownHtml;
                    const firstHeading = tempDiv.querySelector('h1, h2, h3, h4, h5, h6');
                    const summaryText = firstHeading ? firstHeading.textContent : `Search Results for: ${query}`;
                    
                    html += `<div class="search-query-wrapper">
                        <div class="search-query">
                            <button class="copy-query-btn" onclick="copyQueryById('${queryId}')" aria-label="Copy search query">Copy</button>
                            <textarea readonly id="${queryId}">${escapeHtml(query)}</textarea>
                        </div>
                    </div>
                    <details class="search-result-collapsible">
                        <summary class="search-result-summary">${escapeHtml(summaryText)}</summary>
                        <div class="search-result">${markdownHtml}</div>
                    </details>`;
                }
                html += `<div class="tool-meta">Duration: ${toolResult.duration}s | Success: ${toolResult.result.success ? 'Yes' : 'No'}</div>`;
            }
            html += `</div>`;
        });
        html += `</div>`;
    }

    // Reasoning
    if (step.content.reasoning) {
        html += `<details class="reasoning-collapsible">
            <summary>Reasoning</summary>
            <div class="reasoning-text">${escapeHtml(step.content.reasoning)}</div>
        </details>`;
    }

    // Evidence/Derivation (final step only)
    if (index === totalSteps - 1) {
        if (step.content.derivation && step.content.derivation.length > 0) {
            html += `<div class="derivation-section"><h4>Derivation</h4><ol>${step.content.derivation.map(d => `<li><strong>${d.principle}</strong>: ${escapeHtml(d.calculation)}</li>`).join('')}</ol></div>`;
        }
        if (step.content.evidence && step.content.evidence.length > 0) {
            html += `<div class="evidence-section"><h4>Evidence</h4><ul>${step.content.evidence.map(e => `<li><strong>${e.source}</strong>: ${escapeHtml(e.content)}</li>`).join('')}</ul></div>`;
        }
    }

    html += `</div></details>`;
    return html;
}

function copyQueryById(queryId) {
    const query = window.queryStore[queryId];
    if (!query) {
        const queryElement = document.getElementById(queryId);
        if (queryElement) {
            window.queryStore[queryId] = queryElement.value || queryElement.textContent;
            return copyQueryById(queryId);
        }
        return;
    }
    
    const queryElement = document.getElementById(queryId);
    const button = queryElement?.closest('.search-query-wrapper')?.querySelector('.copy-query-btn');
    
    navigator.clipboard.writeText(query).then(() => {
        if (button) {
            const originalText = button.textContent;
            button.textContent = 'Copied!';
            button.classList.add('copied');
            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove('copied');
            }, 2000);
        }
    }).catch(err => {
        console.error('Copy failed:', err);
        alert('Failed to copy query');
    });
}

function copyQuery(id) {
    const queryId = `query-${id}`;
    copyQueryById(queryId);
}

async function loadProof(sessionId) {
    try {
        const response = await fetch(`${PROOFS_DIR}${sessionId}.json`);
        if (!response.ok) {
            throw new Error('Failed to load proof');
        }
        const proof = await response.json();
        renderProof(proof);
    } catch (error) {
        console.error('Error loading proof:', error);
        document.getElementById('proofContainer').innerHTML =
            `<div class="loading">Error loading proof: ${error.message}</div>`;
    }
}

function formatRelativeTime(timestamp) {
    if (!timestamp) return 'Unknown';
    try {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffSecs = Math.floor(diffMs / 1000);
        const diffMins = Math.floor(diffSecs / 60);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffSecs < 60) return 'Just now';
        if (diffMins < 60) return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;
        if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
        if (diffDays < 7) return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
        return date.toLocaleDateString();
    } catch (e) {
        return formatTimestamp(timestamp);
    }
}

function copyProofId(proofId, element) {
    navigator.clipboard.writeText(proofId).then(() => {
        const originalText = element.textContent;
        element.textContent = 'Copied!';
        setTimeout(() => {
            element.textContent = originalText;
        }, 2000);
    }).catch(err => {
        console.error('Copy failed:', err);
    });
}

function toggleAllSteps() {
    const steps = document.querySelectorAll('.step-collapsible');
    const allOpen = Array.from(steps).every(step => step.hasAttribute('open'));
    
    steps.forEach(step => {
        if (allOpen) {
            step.removeAttribute('open');
        } else {
            step.setAttribute('open', '');
        }
    });
    
    const btn = document.getElementById('toggleAllBtn');
    if (btn) {
        btn.textContent = allOpen ? 'Expand All' : 'Collapse All';
    }
}

function renderProof(proof) {
    const container = document.getElementById('proofContainer');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    
    let html = '';

    let verdict = 'UNKNOWN';
    if (proof.events) {
        for (let i = proof.events.length - 1; i >= 0; i--) {
            const event = proof.events[i];
            if (event.type === 'model_output' && event.content?.verdict != null) {
                verdict = event.content.verdict;
                break;
            }
        }
    }

    html += `<div class="proof-section">
        <div class="claim">
            <div class="verdict ${verdict}">${verdict}</div>
            ${escapeHtml(proof.claim)}
        </div>
    </div>`;

    const steps = createStepObjects(proof.events);
    const finalStep = steps.length > 0 ? steps[steps.length - 1] : null;
    if (finalStep && finalStep.content.falsifiable_test) {
        html += `<div class="proof-section">
            <div class="falsifiable-test"><h4>Falsifiable Test</h4><p>${escapeHtml(finalStep.content.falsifiable_test)}</p></div>
        </div>`;
    }
    window.currentSteps = steps;
    window.currentProof = proof;
    
    if (steps.length > 0) {
        html += `<div class="proof-section">
            <h2>Proof Steps
                <button id="toggleAllBtn" class="toggle-all-btn" onclick="toggleAllSteps()" aria-label="Toggle all steps">Expand All</button>
            </h2>`;
        steps.forEach((step, index) => {
            html += renderStep(step, index, steps.length);
        });
        html += `</div>`;
    }

    if (proof.metadata) {
        const proofId = proof.proof_id || 'N/A';
        const timestamp = formatTimestamp(proof.timestamp);
        const relativeTime = formatRelativeTime(proof.timestamp);
        
        html += `<div class="proof-section">
            <h2>Metadata</h2>
            <div class="metadata-grid">
                <div class="metadata-item copyable" onclick="copyProofId(${JSON.stringify(proofId)}, this.querySelector('.metadata-value'))" title="Click to copy">
                    <div class="metadata-label">Proof ID</div>
                    <div class="metadata-value">${proofId}</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Timestamp</div>
                    <div class="metadata-value timestamp">
                        <div class="timestamp-full">${timestamp}</div>
                        <div class="timestamp-relative">${relativeTime}</div>
                    </div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Time</div>
                    <div class="metadata-value">${proof.metadata.time_seconds || 0}s</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Total Tokens</div>
                    <div class="metadata-value">${(proof.metadata.tokens?.total || 0).toLocaleString()}</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Cost</div>
                    <div class="metadata-value">$${proof.metadata.cost?.total_usd?.toFixed(6) || '0.000000'}</div>
                </div>
            </div>
        </div>`;
    }

    container.innerHTML = html;
}

function updateNavigation() {
    document.getElementById('prevBtn').disabled = currentIndex === 0;
    document.getElementById('nextBtn').disabled = currentIndex === proofs.length - 1;
    document.getElementById('proofCounter').textContent = `${currentIndex + 1} / ${proofs.length}`;
}

function formatTimestamp(timestamp) {
    if (!timestamp) return 'Unknown';
    try {
        const date = new Date(timestamp);
        return date.toLocaleString();
    } catch (e) {
        return timestamp;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function navigateToProof(direction) {
    if (direction === 'prev' && currentIndex > 0) {
        currentIndex--;
        await loadProof(proofs[currentIndex]);
        updateNavigation();
    } else if (direction === 'next' && currentIndex < proofs.length - 1) {
        currentIndex++;
        await loadProof(proofs[currentIndex]);
        updateNavigation();
    }
}

document.getElementById('prevBtn').addEventListener('click', () => navigateToProof('prev'));
document.getElementById('nextBtn').addEventListener('click', () => navigateToProof('next'));

document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) {
        return;
    }
    
    if (e.key === 'ArrowLeft') {
        e.preventDefault();
        navigateToProof('prev');
    } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        navigateToProof('next');
    }
});

loadProofs();
