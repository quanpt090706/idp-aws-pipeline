variable "project" {
  type    = string
  default = "idp"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.project))
    error_message = "Project must be 2-16 lowercase letters, digits or hyphens."
  }
}
variable "region" {
  type        = string
  description = "Actual region permitted by your Academy lab."
}
variable "aws_profile" {
  type    = string
  default = "academy-lab"
}
variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Use the lab's 12-digit account ID."
  }
}
variable "lambda_role_arn" {
  type        = string
  description = "Existing role with lambda.amazonaws.com trust and TV2 permissions."
  validation {
    condition     = can(regex("^arn:[^:]+:iam::[0-9]{12}:role/.+$", var.lambda_role_arn))
    error_message = "Provide an existing IAM role ARN."
  }
}
variable "workflow_role_arn" {
  type        = string
  default     = null
  description = "Existing role with states.amazonaws.com trust, required for the mock workflow."
  validation {
    condition     = !var.create_mock_workflow || can(regex("^arn:[^:]+:iam::[0-9]{12}:role/.+$", var.workflow_role_arn))
    error_message = "The mock workflow requires an existing role with Step Functions trust."
  }
}
variable "create_mock_workflow" {
  type    = bool
  default = true
}
variable "existing_state_machine_arn" {
  type    = string
  default = null
  validation {
    condition     = var.create_mock_workflow || can(regex("^arn:[^:]+:states:[^:]+:[0-9]{12}:stateMachine:.+$", var.existing_state_machine_arn))
    error_message = "Provide TV4's Standard state machine ARN when create_mock_workflow=false."
  }
}
variable "manage_iam_policies" {
  type    = bool
  default = false
}
variable "enable_processing" {
  type        = bool
  default     = false
  description = "Enable after checking contract, role permissions and workflow."
}
variable "alarm_actions" {
  type    = list(string)
  default = []
}
