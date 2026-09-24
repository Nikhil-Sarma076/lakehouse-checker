locals {
  s3_bucket_arns = [for path in var.s3_table_paths : "arn:aws:s3:::${split("/", path)[0]}"]
  s3_object_arns = [for path in var.s3_table_paths : "arn:aws:s3:::${path}"]
}

data "aws_iam_policy_document" "lakecheck_s3_access" {
  statement {
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = local.s3_bucket_arns
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject"
    ]
    resources = local.s3_object_arns
  }
}

resource "aws_iam_policy" "lakecheck_policy" {
  name        = "lakecheck-s3-access"
  description = "Strict S3 access for lakecheck EKS CronJob"
  policy      = data.aws_iam_policy_document.lakecheck_s3_access.json
}

data "aws_iam_policy_document" "lakecheck_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.cluster_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.cluster_oidc_provider_url}:sub"
      values   = ["system:serviceaccount:${var.k8s_namespace}:${var.k8s_service_account}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.cluster_oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lakecheck_role" {
  name               = "lakecheck-irsa-role"
  assume_role_policy = data.aws_iam_policy_document.lakecheck_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lakecheck_attach" {
  role       = aws_iam_role.lakecheck_role.name
  policy_arn = aws_iam_policy.lakecheck_policy.arn
}

resource "kubernetes_service_account" "lakecheck_sa" {
  metadata {
    name      = var.k8s_service_account
    namespace = var.k8s_namespace
    annotations = {
      "eks.amazonaws.com/role-arn" = aws_iam_role.lakecheck_role.arn
    }
  }
}
