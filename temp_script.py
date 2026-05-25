import pandas as pd
import numpy as np
from sklearn.model_selection import StratifiedKFold
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

# Load the manifest and features (assuming they're in CSV format)
manifest = pd.read_csv('manifest.csv')
features = pd.read_csv('features.csv')

# Ensure the target column exists and is binary
assert 'label' in manifest.columns, "Manifest missing 'label' column"
assert manifest['label'].nunique() == 2, "Label column must be binary"

# Prepare data
X = features.values
y = manifest['label'].values

# 3-fold group stratified split
skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)

results = []

for fold, (train_idx, test_idx) in enumerate(skf.split(X, y)):
    X_train, X_test = X[train_idx], X[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]

    # PCA
    pca = PCA(n_components=0.95)  # Retain 95% variance
    X_train_pca = pca.fit_transform(X_train)
    X_test_pca = pca.transform(X_test)

    # Model 1: PCA + LogisticRegression
    lr = LogisticRegression(max_iter=1000)
    lr.fit(X_train_pca, y_train)
    y_pred_lr = lr.predict(X_test_pca)
    results.append({
        'model': 'PCA + LogisticRegression',
        'fold': fold+1,
        'accuracy': accuracy_score(y_test, y_pred_lr),
        'precision': precision_score(y_test, y_pred_lr),
        'recall': recall_score(y_test, y_pred_lr),
        'f1': f1_score(y_test, y_pred_lr)
    })

    # Model 2: PCA + LinearSVC (decision_function > 0 as positive)
    lsvc = LinearSVC()
    lsvc.fit(X_train_pca, y_train)
    y_pred_lsvc = (lsvc.decision_function(X_test_pca) > 0).astype(int)
    results.append({
        'model': 'PCA + LinearSVC',
        'fold': fold+1,
        'accuracy': accuracy_score(y_test, y_pred_lsvc),
        'precision': precision_score(y_test, y_pred_lsvc),
        'recall': recall_score(y_test, y_pred_lsvc),
        'f1': f1_score(y_test, y_pred_lsvc)
    })

    # Model 3: RandomForestClassifier (small model, random_state=42)
    rfc = RandomForestClassifier(n_estimators=100, random_state=42)
    rfc.fit(X_train_pca, y_train)
    y_pred_rfc = rfc.predict(X_test_pca)
    results.append({
        'model': 'RandomForestClassifier',
        'fold': fold+1,
        'accuracy': accuracy_score(y_test, y_pred_rfc),
        'precision': precision_score(y_test, y_pred_rfc),
        'recall': recall_score(y_test, y_pred_rfc),
        'f1': f1_score(y_test, y_pred_rfc)
    })

# Calculate mean across folds
results_df = pd.DataFrame(results)
mean_results = results_df.groupby('model').mean().round(4)

print("\n=== Model Performance (3-fold mean) ===")
print(mean_results)

# Optional: Check if adjusting the decision threshold for LogisticRegression helps
# (e.g., using predict_proba and a threshold < 0.5)
print("\n=== LogisticRegression threshold check ===")
for fold in range(3):
    X_train_pca, X_test_pca = X_train_pca_fold[fold], X_test_pca_fold[fold]
    y_train, y_test = y_train_fold[fold], y_test_fold[fold]
    # Re-run LogisticRegression with predict_proba
    lr = LogisticRegression(max_iter=1000)
    lr.fit(X_train_pca, y_train)
    probas = lr.predict_proba(X_test_pca)[:, 1]
    # Try threshold 0.3
    y_pred_lr_thres = (probas > 0.3).astype(int)
    acc_thres = accuracy_score(y_test, y_pred_lr_thres)
    print(f"Fold {fold+1}: threshold 0.3 -> accuracy {acc_thres:.4f}")
    # Try threshold 0.2
    y_pred_lr_thres = (probas > 0.2).astype(int)
    acc_thres = accuracy_score(y_test, y_pred_lr_thres)
    print(f"Fold {fold+1}: threshold 0.2 -> accuracy {acc_thres:.4f}")

