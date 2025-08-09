# AI Code Review & Refactoring Bot

An intelligent GitHub-integrated bot that automatically reviews pull requests, suggests improvements, and can even create fix PRs. It uses multiple AI models and static analysis tools to provide comprehensive code reviews.

## Features

- 🔍 **Automated Code Review**: Analyzes PRs using multiple AI models (GPT-4, Claude, Code Llama)
- 🛠️ **Static Analysis**: Runs linters (Pylint, ESLint) on changed files
- 🧪 **Test Verification**: Executes tests to ensure code quality
- 🔧 **Auto-fix Generation**: Creates patches for common issues
- 🚀 **Fix PR Creation**: Automatically opens PRs with validated fixes
- 📊 **Multi-model Consensus**: Uses multiple AI models for better accuracy
- 🔄 **Async Processing**: Handles reviews in background using Celery

## Architecture

The system consists of multiple AI agents coordinated by an orchestrator:

1. **Analysis Agent**: Parses linter and test outputs
2. **Reviewer Agent**: Performs AI-powered code review using multiple models
3. **Refactoring Agent**: Generates code patches for identified issues
4. **Test Runner Agent**: Validates patches in isolated environments
5. **PR Commenter Agent**: Posts review comments and creates fix PRs

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- A GitHub account with permissions to create GitHub Apps
- API keys for AI services (OpenAI, Anthropic, etc.)

## Setup Instructions

### 1. Create a GitHub App

1. Go to your GitHub Settings > Developer settings > GitHub Apps
2. Click "New GitHub App"
3. Fill in the following:
   - **App name**: Choose a unique name (e.g., "My-AI-Code-Reviewer")
   - **Homepage URL**: Your app URL or GitHub repo
   - **Webhook URL**: `https://your-domain.com/webhook/github`
   - **Webhook secret**: Generate a secure random string
4. Set permissions:

   - **Repository permissions**:
     - Contents: Read & Write
     - Issues: Write
     - Pull requests: Read & Write
     - Checks: Write
   - **Subscribe to events**:
     - Pull request
     - Pull request review
     - Pull request review comment

5. Create the app and note down:
   - App ID
   - Generate and download a private key (`.pem` file)

### 2. Local Development Setup

1. **Clone the repository**:

   ```bash
   git clone <your-repo-url>
   cd ai-code-reviewer
   ```

2. **Set up environment variables**:

   ```bash
   cp env.example .env
   ```

   Edit `.env` and fill in:

   - `GITHUB_APP_ID`: Your GitHub App ID
   - `GITHUB_WEBHOOK_SECRET`: Your webhook secret
   - `OPENAI_API_KEY`: Your OpenAI API key
   - `ANTHROPIC_API_KEY`: Your Anthropic API key (optional)
   - Other API keys as needed

3. **Place your GitHub App private key**:

   ```bash
   cp /path/to/your/private-key.pem github-app-key.pem
   ```

4. **Start the services**:

   ```bash
   docker-compose up --build
   ```

5. **Verify the services are running**:
   - API: http://localhost:8000
   - API Health: http://localhost:8000/health
   - Flower (Celery monitoring): http://localhost:5555

### 3. Expose Local Development to GitHub

For local development, you need to expose your webhook endpoint to the internet:

1. **Using ngrok** (recommended):
   ```bash
   ngrok http 8000
   ```
2. Update your GitHub App's webhook URL to the ngrok URL:
   ```
   https://your-subdomain.ngrok.io/webhook/github
   ```

### 4. Install the GitHub App

1. Go to your GitHub App settings
2. Click "Install App"
3. Choose the repositories you want to monitor
4. The bot will now receive webhooks for PR events

## Production Deployment

### Option 1: Deploy to Railway

1. **Create a Railway account** at https://railway.app

2. **Create a new project** and add services:

   - PostgreSQL (provisioned automatically)
   - Redis (provisioned automatically)
   - Add service from GitHub repo

3. **Set environment variables** in Railway dashboard:

   ```
   GITHUB_APP_ID=your_app_id
   GITHUB_WEBHOOK_SECRET=your_webhook_secret
   GITHUB_APP_PRIVATE_KEY_PATH=/app/github-app-key.pem
   OPENAI_API_KEY=your_openai_key
   # ... other keys
   ```

4. **Add your private key** as a volume or base64-encoded env var

5. **Deploy** and get your public URL

6. **Update GitHub App** webhook URL to Railway URL

### Option 2: Deploy to Render

1. **Create a Render account** at https://render.com

2. **Create services**:

   - Web Service (for API)
   - Background Worker (for Celery)
   - PostgreSQL database
   - Redis instance

3. **Configure build settings**:

   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

4. **Set environment variables** in Render dashboard

5. **Deploy** and update GitHub webhook URL

### Option 3: Deploy to AWS/GCP/Azure

1. **Use container services**:

   - AWS: ECS with Fargate
   - GCP: Cloud Run
   - Azure: Container Instances

2. **Set up managed services**:

   - Database: RDS/Cloud SQL/Azure Database
   - Redis: ElastiCache/MemoryStore/Azure Cache

3. **Configure load balancer** for HTTPS

4. **Set up secrets management** for API keys

## Usage

Once deployed and installed on repositories:

1. **Create or update a PR** in a monitored repository

2. **The bot will automatically**:

   - Run linters on changed files
   - Perform AI code review
   - Post review comments with findings
   - Create a fix PR if issues can be auto-fixed

3. **Review the bot's comments** which include:
   - Summary of changes
   - Identified issues (prioritized by severity)
   - Suggestions for improvement
   - Link to auto-fix PR (if applicable)

## Configuration

### Customizing Review Behavior

Edit `backend/config.py` to adjust:

- AI model selection
- Linter configurations
- Test runner settings
- Review thresholds

### Adding New Linters

1. Add linter to `requirements.txt`
2. Implement in `backend/services/linter_service.py`
3. Update `LinterService.linters` mapping

### Adding New AI Models

1. Add model client to `requirements.txt`
2. Initialize in `backend/agents/reviewer_agent.py`
3. Add to `ReviewerAgent.models` dictionary

## Monitoring

- **Celery Tasks**: Visit http://localhost:5555 (Flower)
- **API Logs**: `docker-compose logs backend`
- **Worker Logs**: `docker-compose logs worker`
- **Database**: Connect to PostgreSQL on port 5432

## Troubleshooting

### Bot not responding to PRs

1. Check webhook delivery in GitHub App settings
2. Verify webhook secret matches
3. Check API logs for errors
4. Ensure app is installed on the repository

### AI reviews failing

1. Verify API keys are set correctly
2. Check rate limits for AI services
3. Review worker logs for errors
4. Ensure sufficient memory for models

### Tests not running

1. Verify test commands in `TestRunnerService`
2. Check if test dependencies are installed
3. Review file path mappings
4. Check worker has repository access

## Development

### Running Tests

```bash
# Run unit tests
docker-compose run backend pytest

# Run with coverage
docker-compose run backend pytest --cov=backend
```

### Adding New Features

1. Create feature branch
2. Implement changes
3. Add tests
4. Update documentation
5. Submit PR

## Security Considerations

- Store private keys securely
- Use environment variables for secrets
- Implement rate limiting
- Validate webhook signatures
- Limit repository permissions
- Regular security updates

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:

1. Check existing issues on GitHub
2. Review logs for error details
3. Create detailed bug reports
4. Include reproduction steps

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Ensure linting passes
5. Submit a pull request

---

Built with ❤️ using FastAPI, Celery, LangChain, and multiple AI models.
