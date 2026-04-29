"""Tests for classifying unified diff hunks by API-conventions relevance."""

import diff_hunk_classification


def test_validation_hunk_is_retained_as_api_conventions_candidate() -> None:
    patch = """diff --git a/pkg/apis/storage/validation/validation.go b/pkg/apis/storage/validation/validation.go
--- a/pkg/apis/storage/validation/validation.go
+++ b/pkg/apis/storage/validation/validation.go
@@ -1,3 +1,4 @@
+allErrs = append(allErrs, field.Invalid(fldPath, nodeID, "must be 256 characters or less"))
"""

    result = diff_hunk_classification.classify_patch(patch)

    assert result.hunks[0].classification == diff_hunk_classification.HunkClassification.API_VALIDATION
    assert result.candidate_hunks == result.hunks
    assert result.excluded_hunks == ()


def test_metrics_hunk_is_excluded_even_when_it_mentions_resource_version() -> None:
    patch = """diff --git a/pkg/metrics/metrics.go b/pkg/metrics/metrics.go
--- a/pkg/metrics/metrics.go
+++ b/pkg/metrics/metrics.go
@@ -1,3 +1,4 @@
+watchCacheResourceVersion.Set(float64(resourceVersion % 1000000000000000))
"""

    result = diff_hunk_classification.classify_patch(patch)

    assert result.hunks[0].classification == diff_hunk_classification.HunkClassification.NON_API_METRIC
    assert result.candidate_hunks == ()
    assert result.excluded_hunks == result.hunks


def test_version_registration_hunk_is_retained_as_api_candidate() -> None:
    patch = """diff --git a/apis/example/install/install.go b/apis/example/install/install.go
--- a/apis/example/install/install.go
+++ b/apis/example/install/install.go
@@ -1,3 +1,4 @@
-utilruntime.Must(v1alpha1.AddToScheme(scheme))
-utilruntime.Must(scheme.SetVersionPriority(v1.SchemeGroupVersion, v1alpha1.SchemeGroupVersion))
"""

    result = diff_hunk_classification.classify_patch(patch)

    assert result.hunks[0].classification == diff_hunk_classification.HunkClassification.API_CONVERSION_VERSIONING
    assert result.candidate_hunks == result.hunks


def test_dependency_only_patch_is_excluded() -> None:
    patch = """diff --git a/staging/src/k8s.io/apiserver/go.mod b/staging/src/k8s.io/apiserver/go.mod
--- a/staging/src/k8s.io/apiserver/go.mod
+++ b/staging/src/k8s.io/apiserver/go.mod
@@ -1,3 +1,3 @@
-go.etcd.io/etcd/client/v3 v3.6.6
+go.etcd.io/etcd/client/v3 v3.6.7
"""

    result = diff_hunk_classification.classify_patch(patch)

    assert result.hunks[0].classification == diff_hunk_classification.HunkClassification.NON_API_DEPENDENCY
    assert result.has_api_conventions_candidates is False


def test_context_plumbing_in_watch_handler_is_excluded() -> None:
    patch = """diff --git a/pkg/endpoints/handlers/watch.go b/pkg/endpoints/handlers/watch.go
--- a/pkg/endpoints/handlers/watch.go
+++ b/pkg/endpoints/handlers/watch.go
@@ -1,3 +1,3 @@
-watchEncoder := newWatchEncoder(context.TODO(), gvr, s.EmbeddedEncoder, s.Encoder, framer)
+watchEncoder := newWatchEncoder(ctx, gvr, s.EmbeddedEncoder, s.Encoder, framer)
"""

    result = diff_hunk_classification.classify_patch(patch)

    assert result.hunks[0].classification == diff_hunk_classification.HunkClassification.NON_API_CONTEXT_PLUMBING
    assert result.has_api_conventions_candidates is False
