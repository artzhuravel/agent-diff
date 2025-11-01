"""
Standalone GraphQL server for testing Linear API with Apollo Studio.

Usage:
    python test_graphql_server.py

Then point Apollo Studio to: http://localhost:4000/graphql
"""

import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine
from starlette.applications import Starlette
from ariadne import load_schema_from_path, make_executable_schema
from ariadne.asgi import GraphQL
from src.services.linear.api.resolvers import query, mutation
from src.platform.isolationEngine.session import SessionManager
from src.platform.isolationEngine.core import CoreIsolationEngine
from src.platform.isolationEngine.environment import EnvironmentHandler


# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/diff_the_universe")
ENV_ID = os.getenv("LINEAR_ENV_ID")  # You'll set this after creating an environment

# Initialize database connections
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
sessions = SessionManager(engine)
environment_handler = EnvironmentHandler(session_manager=sessions)
core_isolation_engine = CoreIsolationEngine(
    sessions=sessions,
    environment_handler=environment_handler
)


def create_app():
    """Create a simple GraphQL app for testing."""

    # Load Linear GraphQL schema
    schema_path = "src/services/linear/api/schema/Linear-API.graphql"
    type_defs = load_schema_from_path(schema_path)
    schema = make_executable_schema(type_defs, query, mutation)

    # Create context function
    def context_value(request):
        """Create context for GraphQL resolvers with isolated session."""
        env_id = ENV_ID

        if not env_id:
            print("\nERROR: LINEAR_ENV_ID not set!")
            print("Create an environment first:")
            print('  curl -X POST http://localhost:8000/api/platform/initEnv \\')
            print('    -H "Content-Type: application/json" \\')
            print('    --data \'{"service": "linear", "template": "linear_default", "ttl": 3600}\'')
            print("\nThen export the environment_id:")
            print('  export LINEAR_ENV_ID="your-environment-id-here"')
            raise PermissionError("LINEAR_ENV_ID environment variable not set")

        session = sessions.get_session_for_environment(env_id)

        return {
            "request": request,
            "session": session,
            "environment_id": env_id,
            "user_id": "U01AGENT",
            "impersonate_email": "agent@example.com",
        }

    # Create GraphQL app
    graphql_app = GraphQL(schema, context_value=context_value, debug=True)

    # Create Starlette app
    app = Starlette(debug=True)
    app.mount("/graphql", graphql_app)

    return app


if __name__ == "__main__":
    import uvicorn

    print("\n" + "="*70)
    print("Linear GraphQL Test Server for Apollo Studio")
    print("="*70)

    if not ENV_ID:
        print("\n⚠️  LINEAR_ENV_ID not set!")
        print("\n1. First, ensure the backend is running:")
        print("   cd ops && docker compose up -d")
        print("\n2. Create a Linear environment:")
        print('   curl -X POST http://localhost:8000/api/platform/initEnv \\')
        print('     -H "Content-Type: application/json" \\')
        print('     --data \'{"service": "linear", "template": "linear_default", "ttl": 36000}\'')
        print("\n3. Export the environment_id from the response:")
        print('   export LINEAR_ENV_ID="paste-environment-id-here"')
        print("\n4. Run this server again:")
        print("   python test_graphql_server.py")
        sys.exit(1)

    print(f"\n✓ Using environment: {ENV_ID}")
    print("\nServer starting on: http://localhost:4000/graphql")
    print("\nConfigure Apollo Studio:")
    print("  - Endpoint: http://localhost:4000/graphql")
    print("  - No authentication needed")
    print("\nExample query to try:")
    print("""
    {
      issues(first: 5) {
        edges {
          node {
            id
            title
            identifier
            state {
              name
            }
          }
          cursor
        }
        pageInfo {
          hasNextPage
          hasPreviousPage
          startCursor
          endCursor
        }
      }
    }
    """)
    print("="*70 + "\n")

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=4000, log_level="info")
