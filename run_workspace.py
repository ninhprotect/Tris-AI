"""Compatibility entrypoint. The workspace is the main app on :7860 now."""
from workspace_host import create_application, main

# Preserve uvicorn run_workspace:app for external tooling.
if __name__ == "__main__":
    main()
else:
    app = create_application()
