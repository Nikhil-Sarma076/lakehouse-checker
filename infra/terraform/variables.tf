variable "cluster_oidc_provider_arn" {
  description = "The ARN of the EKS cluster OIDC provider (e.g., arn:aws:iam::123:oidc-provider/oidc.eks...)"
  type        = string
}

variable "cluster_oidc_provider_url" {
  description = "The URL of the EKS cluster OIDC provider (without the https://)"
  type        = string
}

variable "k8s_namespace" {
  description = "Kubernetes namespace where lakecheck will run"
  type        = string
  default     = "data-platform"
}

variable "k8s_service_account" {
  description = "Name of the Kubernetes Service Account for lakecheck"
  type        = string
  default     = "lakecheck-sa"
}

variable "s3_table_paths" {
  description = "List of S3 buckets/paths the tool is allowed to scan (e.g. ['my-bucket/tables/*'])"
  type        = list(string)
}
