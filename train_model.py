import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

if len(sys.argv) > 1:
    shutil.copy(ROOT / "data" / sys.argv[1], ROOT / "data" / "container_history.csv")
    print(f"Using data/{sys.argv[1]}")

from sklearn.model_selection import cross_val_score
from sklearn.tree import DecisionTreeClassifier, export_text

from model import FEATURES, ROWS, row_to_features

X = [row_to_features(r) for r in ROWS]
y = [r["Recommended Action"] for r in ROWS]

tree = DecisionTreeClassifier(max_depth=5, random_state=0)
scores = cross_val_score(tree, X, y, cv=5)
print(f"Accuracy on unseen rows: {scores.mean():.0%} (5-fold cross-validation)\n")

tree.fit(X, y)
print("Rules the tree learned:")
print(export_text(tree, feature_names=FEATURES))
