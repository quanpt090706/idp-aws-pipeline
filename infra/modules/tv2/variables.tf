variable "name_prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,39}$", var.name_prefix))
    error_message = "Use a 2-40 character lowercase resource prefix."
  }
}
variable "region" { type = string }
variable "upload_bucket_name" { type = string }
variable "documents_table_name" { type = string }
variable "state_machine_arn" {
  type = string
  validation {
    condition     = can(regex("^arn:[^:]+:states:[^:]+:[0-9]{12}:stateMachine:[A-Za-z0-9_-]+(:[A-Za-z0-9_-]+)?$", var.state_machine_arn))
    error_message = "Provide a Standard state machine ARN, not a Distributed Map ARN."
  }
}
variable "lambda_role_arn" {
  type        = string
  description = "Existing role with Lambda trust and the documented service permissions."
}
variable "artifact_directory" {
  type        = string
  description = "Directory containing ZIPs built by scripts/build_tv2.py."
}
variable "enable_processing" {
  type    = bool
  default = false
}
variable "manage_bucket_notification" {
  type        = bool
  default     = false
  description = "Opt in only for a dedicated bucket; otherwise merge into the existing notification resource."
}
variable "manage_iam_policies" {
  type        = bool
  default     = false
  description = "Keep false for Academy roles you cannot modify; existing role must have the listed permissions."
}
variable "alarm_actions" {
  type        = list(string)
  default     = []
  description = "Existing SNS topic ARNs for notifications, if allowed by the lab."
}
variable "tags" {
  type    = map(string)
  default = {}
}
