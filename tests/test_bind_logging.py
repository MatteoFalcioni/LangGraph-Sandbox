#!/usr/bin/env python3
"""
Test script to demonstrate the new BIND mode session logging functionality.
"""

import sys
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from sandbox.session_manager import SessionManager, SessionStorage, DatasetAccess


def test_bind_logging():
    """Test the new BIND mode logging functionality."""
    print("Testing BIND mode session logging...")
    
    # Create session manager in BIND mode
    manager = SessionManager(
        session_storage=SessionStorage.BIND,
        dataset_access=DatasetAccess.NONE,
        session_root=Path("./sessions")
    )
    
    try:
        # Start a new session
        session_id = manager.start("test-logging")
        print(f"Started session: {session_id}")
        
        # Execute some test code
        print("Executing test code...")
        result1 = manager.exec(session_id, """
import pandas as pd
import numpy as np

# Create some test data
df = pd.DataFrame({
    'x': np.arange(10),
    'y': np.random.randn(10)
})

print("DataFrame created:")
print(df.head())

# Create a simple plot
import matplotlib.pyplot as plt
plt.figure(figsize=(8, 6))
plt.plot(df['x'], df['y'], 'o-')
plt.title('Test Plot')
plt.xlabel('X')
plt.ylabel('Y')

# Save plot to artifacts
import os
os.makedirs('/session/artifacts', exist_ok=True)
plt.savefig('/session/artifacts/test_plot.png')
plt.close()

print("Plot saved to artifacts!")
""")
        
        print(f"Execution 1 result: {result1['ok']}")
        print(f"Artifacts created: {len(result1['artifacts'])}")
        
        # Execute more code to test state persistence
        print("Executing more test code...")
        result2 = manager.exec(session_id, """
# Use the existing DataFrame
print("Using existing DataFrame:")
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")

# Create another artifact
with open('/session/artifacts/test_data.txt', 'w') as f:
    f.write(f"DataFrame shape: {df.shape}\n")
    f.write(f"Mean of y: {df['y'].mean():.4f}\n")

print("Data summary saved!")
""")
        
        print(f"Execution 2 result: {result2['ok']}")
        print(f"Artifacts created: {len(result2['artifacts'])}")
        
        # Stop the session
        manager.stop(session_id)
        print("Session stopped")
        
        # Now let's inspect what was saved
        session_dir = Path("./sessions") / session_id
        print(f"\nSession directory: {session_dir}")
        
        # Check what files were created
        print("\nFiles created:")
        for file_path in session_dir.rglob("*"):
            if file_path.is_file():
                size = file_path.stat().st_size
                print(f"  {file_path.relative_to(session_dir)} ({size} bytes)")
        
        print("\n" + "="*50)
        print("Use the session viewer to inspect the logs:")
        print(f"python src/sandbox/session_viewer.py sessions/{session_id}")
        
    except Exception as e:
        print(f"Error during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up
        try:
            manager.stop(session_id)
        except:
            pass


if __name__ == "__main__":
    test_bind_logging()
