# Coder Agent (`coder-agent`) v2.0

> A production-grade, highly resilient **AI Coding Agent CLI** comparable to Anthropic's Claude Code and OpenAI's Codex CLI. It understands entire repositories, performs precise hunk replacements, auto-creates Git checkpoints, executes test suites with traceback diagnostics, redacts secrets, and self-heals until tests pass.

---

## Key Capabilities

- **Resilient Multi-Provider Orchestration**: Seamlessly swap between **Anthropic Claude**, **AWS Bedrock (Converse API)**, **Azure OpenAI**, and **Local LLMs (Ollama / LM Studio / vLLM)**. Built-in exponential backoff with full jitter automatically recovers from HTTP 429 rate limits, 500/503 errors, and temporary network interruptions.
- **Precise Search-and-Replace Hunk Editing (`edit_file`)**: Eliminates destructive full-file overwrites. Targets exact code chunks with trailing-whitespace tolerance and line-numbered disambiguation, saving thousands of tokens and preserving existing formatting.
- **Git Checkpoint & Instant Rollback (`/undo`)**: Automatically creates workspace git checkpoints before tool side-effects take place. Revert any buggy modifications or unwanted changes with a single `/undo` command.
- **Repository Intelligence & Hybrid Search**:
  - **AST Symbol Indexer**: Extracts classes, methods, functions, and imports across Python, TypeScript, JavaScript, Go, and Rust.
  - **PageRank Repo Map**: Generates token-budgeted (<1,500 tokens) architectural context maps embedded in system prompts.
  - **Hybrid Code Search**: Ranks code locations by combining symbol matching (10.0 score) with lexical token matching.
- **Context Compaction & Sliding Window**: Automatically compacts older conversation turns into synthesized milestones at 70% context capacity, ensuring long-running sessions never overflow LLM token limits.
- **Persistent SQLite Session Store**: Saves all session turns, tool calls, and checkpoints to SQLite (`.coder-agent/sessions.db`). Continue any past session with `--resume`.
- **Targeted Test Runner & Diagnostician (`run_tests`)**: Automatically detects test runners (`pytest`, `npm test`, `cargo test`, `go test`), scopes execution to modified files, and formats tracebacks into prioritized diagnostic blocks.
- **Guarded Security Boundary**:
  - **Symlink Traversal Shield**: Resolves canonical paths (`os.path.realpath`) to prevent jailbreak attacks outside workspace roots.
  - **Secret Detection & Redaction**: Scans prompts and tool outputs for AWS keys, GitHub tokens, OpenAI/Anthropic API keys, and private keys, redacting them to `[REDACTED_*]` before external transmission.
  - **Command Blocklist & Approvals**: Blocks dangerous shell patterns (`rm -rf /`, `mkfs`, fork bombs) and requests interactive `[y/N]` confirmation in destructive mode.
- **Real-Time Token & Cost Analytics**: Real-time token monitoring and pricing calculator for input/output tokens per provider. Inspect with `/cost` or at turn completion.
- **Model Context Protocol (MCP) Integration**: Connect external tools via `.coder-agent/mcp.json` over stdio JSON-RPC transport.
- **Autonomous Self-Review Pass**: Automatically verifies AST syntax on modified Python files, triggering a self-correction turn in the agent loop if syntax errors or regressions are detected.
- **Advanced Interactive REPL**: Multi-turn conversational continuity with graceful signal handling (`Ctrl+C` cancels current streaming/command without killing the CLI) and full slash command routing.

---

## Architecture

```mermaid
flowchart TD
    subgraph UI_Layer ["CLI & Interactive Experience"]
        CLI["CLI Entry (`coder-agent`)"]
        REPL["Persistent REPL (`interactive.py`)"]
        Signals["Signal Handler (`SIGINT` Trap)"]
        SlashCmd["Slash Commands (`commands.py`)"]
    end

    subgraph Core_Engine ["Orchestration & Intelligence Core"]
        AgentCore["Agent Loop (`agent.py`)"]
        SelfReview["Self-Review Engine (`agent.py`)"]
        Compactor["Context Compactor & Budgeter (`compactor.py`)"]
        RepoMapEngine["AST Symbol Indexer & RepoMap (`indexer/`)"]
        HybridSearch["Hybrid Code Search (`indexer/search.py`)"]
    end

    subgraph Memory_Safety ["Persistence & Boundary Guard"]
        SQLiteStore["SQLite Session Store (`storage/db.py`)"]
        StoreModels["Storage Record Models (`storage/models.py`)"]
        GitMgr["Git Checkpoint & Rollback Engine (`git.py`)"]
        SafetyShield["Safety & Symlink Shield (`safety.py`)"]
        SecretMasker["Secret Scanner & Redactor (`safety_secrets.py`)"]
    end

    subgraph Tools_Subsystem ["Workspace Tools & MCP"]
        ToolReg["Tool Registry (Dynamic + Parallel)"]
        EditTool["`edit_file` (Search & Replace)"]
        TestTool["`run_tests` (Targeted Diagnostician & Guarded)"]
        GitTool["`git_diff` (Self-Inspection)"]
        MCPClient["MCP Client over stdio (`mcp/`)"]
        AtomicTools["read_file / write_file / delete_file / run_command / search_code"]
    end

    subgraph Providers_Subsystem ["Resilient Multi-Provider LLMs"]
        Resilience["Exponential Backoff & Jitter (`resilience.py`)"]
        Cost["Token & Cost Calculator (`cost.py`)"]
        Backends["Anthropic | Bedrock | Azure OpenAI | Ollama"]
    end

    CLI --> REPL
    REPL --> Signals
    REPL --> SlashCmd
    REPL --> AgentCore

    AgentCore --> SelfReview
    AgentCore --> Compactor
    AgentCore --> SafetyShield
    AgentCore --> Tools_Subsystem
    AgentCore --> RepoMapEngine
    AgentCore --> HybridSearch
    AgentCore --> SQLiteStore
    SQLiteStore --> StoreModels
    AgentCore --> GitMgr

    Tools_Subsystem --> SafetyShield
    SafetyShield --> SecretMasker
    SecretMasker --> Providers_Subsystem
    Providers_Subsystem --> Resilience
    Resilience --> Backends
```

---

## Installation

### Prerequisites
- Python 3.11+
- Virtual environment (recommended)
- Git (recommended for checkpoints)

### Setup
```bash
# Clone the repository
git clone https://github.com/Akash-Yadav25/sidewinder-coding-assitant-.git
cd sidewinder-coding-assitant-

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with development dependencies
pip install -e ".[dev]"
```

Verify installation:
```bash
coder-agent --version
# Output: coder-agent 2.0.0
```

---

## Configuration

Configuration can be set via environment variables, CLI options, or a `.coder-agent.json` file in your workspace root.

```bash
cp .env.example .env
```

### 1. Anthropic (Default)
```bash
export CODER_AGENT_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-api03-...
export CODER_AGENT_MODEL=claude-3-5-sonnet-20241022
```

### 2. AWS Bedrock (Converse API)
```bash
export CODER_AGENT_PROVIDER=bedrock
export AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export CODER_AGENT_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0
```

### 3. Azure OpenAI
```bash
export CODER_AGENT_PROVIDER=azure
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
export AZURE_OPENAI_API_KEY=your-api-key
export AZURE_OPENAI_API_VERSION=2024-10-01-preview
export CODER_AGENT_MODEL=gpt-4o
```

### 4. Ollama / Local LLM (OpenAI-Compatible)
Ensure Ollama is running locally with a tool-calling model:
```bash
ollama run llama3.2
export CODER_AGENT_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434/v1
export CODER_AGENT_MODEL=llama3.2
```

---

## Usage

### Direct Task Execution
Execute a requirement directly and let the agent inspect the codebase, implement changes, verify with tests, and display unified diffs:

```bash
coder-agent "Fix the division by zero edge case in calculator.py and ensure tests pass"
```

Target a specific repository directory:
```bash
coder-agent --project-dir ./examples/sample_project "Run pytest and fix all failing tests"
```

Select a specific provider and model:
```bash
coder-agent -p bedrock -m anthropic.claude-3-5-sonnet-20241022-v2:0 "Add type hints to auth/router.py"
```

### Interactive REPL Mode
Launch an ongoing conversational coding session:

```bash
coder-agent -i
```

Resume a prior session:
```bash
# Resume latest session
coder-agent -i --resume

# Resume specific session by ID
coder-agent -i --resume sess_1731456000
```

### Slash Commands Reference

| Slash Command | Description |
| :--- | :--- |
| `/diff` | Display colorized git diff of all changes made during the session |
| `/undo` | Rollback workspace to the pre-task git checkpoint |
| `/commit [msg]` | Safely stage and commit changes to Git (excluding internal `.coder-agent/`) |
| `/compact` | Compact message history into synthesized milestones |
| `/cost` | Display cumulative token metrics and estimated USD cost |
| `/model [name]` | Inspect active model settings or switch provider/model on the fly |
| `/history` | Display the last 10 conversation turns in a structured table |
| `/reset` | Clear active conversation history while keeping the session alive |
| `/config` | Print active CLI and model configuration |
| `/clear` | Clear the terminal screen |
| `/help` | Display guidance on all slash commands |
| `/exit` or `/quit` | Terminate the interactive session |

---

## Safety & Security Policies

Configure safety behavior with `--approval`:

| Approval Mode | Overwriting Files (`write_file`, `edit_file`) | Deleting Files | Shell & Test Commands | Creating New Files |
| :--- | :--- | :--- | :--- | :--- |
| `destructive` *(default)* | Prompts with unified diff `[y/N]` | Prompts `[y/N]` | Prompts `[y/N]` | Auto-approved |
| `always` | Prompts `[y/N]` | Prompts `[y/N]` | Prompts `[y/N]` | Prompts `[y/N]` |
| `never` *(CI/Tests)* | Auto-approved | Auto-approved | Auto-approved | Auto-approved |

- **Symlink Traversal Guard**: Canonical paths are resolved before every file read or write. Access outside the workspace root is rejected with a `Security violation`.
- **Secret Scanner**: High-entropy API keys, AWS credentials, and private keys are redacted to `[REDACTED_*]` before being sent to LLMs.
- **Command Blocklist**: Automatically rejects dangerous patterns (`rm -rf /`, `sudo`, `mkfs`, fork bombs, etc.).

---

## Tools Reference

The agent utilizes standard, provider-agnostic tools:
1. `edit_file`: Precise search-and-replace hunk editing with fuzzy matching and collision rejection.
2. `read_file`: Reads files with optional line-number ranges.
3. `write_file`: Creates new files or overwrites existing files with diff previews.
4. `delete_file`: Deletes files with confirmation.
5. `list_directory`: Recursively inspects file trees, respecting `.gitignore` and default exclusions.
6. `search_code`: Scans files using regex or text patterns.
7. `run_tests`: Targeted test runner with traceback diagnostician (pytest, npm, cargo, go).
8. `run_command`: Executes general shell commands within the project root.
9. `git_diff`: Allows the agent to self-inspect unstaged modifications.

---

## Evaluation Benchmark (`evals/`)

Coder Agent includes an automated evaluation harness inspired by SWE-bench for benchmarking task completion, token efficiency, and recovery:

```bash
# Run evaluation test suite
pytest tests/test_evals.py tests/test_benchmark_tasks.py -v
```

Tasks are defined in `evals/tasks/benchmark_tasks.py`:
- `bugfix_zerodiv`: ZeroDivisionError diagnosis and fix.
- `feature_power`: Adding exponentiation with negative and zero exponents.
- `refactor_type_hints`: Adding complete type hints and docstrings verified via AST.

---

## Automated Test Suite

Run all 128 unit and integration tests:

```bash
pytest tests/ -v
```

```text
============================= 128 passed in 2.25s ==============================
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
