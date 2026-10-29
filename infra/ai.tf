# Paste an agenda (was infra/ai.yml): the agenda parser behind its own public
# function URL. Same backend image, another handler, outside the VPC: it needs
# no database, and reaches Bedrock (or the Claude API) and Cognito's signing
# keys over the internet.

locals {
  # Names CloudFormation generated. Kept as they are so every import is in place.
  parser_role_name               = "${var.project_name}-ai-ParserRole-obsAxq4CzhVx"
  parser_url_statement_id        = "${var.project_name}-ai-ParserUrlPermission-0z09tJvHuEQr"
  parser_url_invoke_statement_id = "${var.project_name}-ai-ParserUrlInvokePermission-eQW0bbRW3bVL"
}

resource "aws_iam_role" "parser" {
  name = local.parser_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "parser_basic_execution" {
  role       = aws_iam_role.parser.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# bedrock-mantle for the Messages API, bedrock:InvokeModel for Converse. "*" for
# now; narrowing it is a discussion question in the lab.
resource "aws_iam_role_policy" "parser_call_bedrock" {
  name = "call-bedrock"
  role = aws_iam_role.parser.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "bedrock-mantle:CreateInference",
        "bedrock:InvokeModel",
      ]
      Resource = "*"
    }]
  })
}

# GetParameter on exactly one parameter. The aws/ssm key's own policy lets SSM
# decrypt it for this account, so no kms:Decrypt is needed.
resource "aws_iam_role_policy" "parser_read_claude_api_key" {
  name = "read-claude-api-key"
  role = aws_iam_role.parser.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "ssm:GetParameter"
      # The name starts with "/", so it follows "parameter" directly.
      Resource = "arn:${local.partition}:ssm:${local.region}:${local.account_id}:parameter${var.anthropic_api_key_parameter}"
    }]
  })
}

resource "aws_cloudwatch_log_group" "parser" {
  name              = "/aws/lambda/${var.project_name}-agenda-parser"
  retention_in_days = 7
}

resource "aws_lambda_function" "parser" {
  function_name = "${var.project_name}-agenda-parser"
  description   = "Parses pasted text into a suggested agenda with Claude on Bedrock"
  package_type  = "Image"
  image_uri     = local.image_uri
  architectures = [var.architecture]
  role          = aws_iam_role.parser.arn
  # A parse takes 2-8 s; one retry after an invalid answer doubles that.
  memory_size = 512
  timeout     = 30

  image_config {
    command = ["app.ai.agenda_lambda.handler"]
  }

  # The template set no LogFormat, so it is Text.
  logging_config {
    log_group  = aws_cloudwatch_log_group.parser.name
    log_format = "Text"
  }

  # No vpc_config: the parser needs no database.
  environment {
    variables = {
      PARSER_PROVIDER = var.parser_provider
      PARSER_MODEL    = var.parser_model
      PARSER_REGION   = local.region
      # The parameter's name, never the key: the handler reads the value at start.
      ANTHROPIC_API_KEY_PARAMETER = var.anthropic_api_key_parameter
      COGNITO_REGION              = local.region
      COGNITO_USER_POOL_ID        = aws_cognito_user_pool.users.id
      COGNITO_CLIENT_ID           = aws_cognito_user_pool_client.web.id
      LOG_LEVEL                   = var.log_level
    }
  }

  # GitHub Actions deploys the image.
  lifecycle {
    ignore_changes = [image_uri]
  }
}

# Public: the handler checks the Cognito access token itself. CORS is set here
# (the handler sets no CORS headers), and the URL answers the preflight.
resource "aws_lambda_function_url" "parser" {
  function_name      = aws_lambda_function.parser.function_name
  authorization_type = "NONE"
  invoke_mode        = "BUFFERED"

  cors {
    allow_origins = local.site_origins
    allow_methods = ["POST"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 300
  }
}

# A public URL needs both statements: InvokeFunctionUrl for the URL itself, and
# InvokeFunction limited to calls that arrive through it.
resource "aws_lambda_permission" "parser_url" {
  statement_id           = local.parser_url_statement_id
  function_name          = aws_lambda_function.parser.function_name
  action                 = "lambda:InvokeFunctionUrl"
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "parser_url_invoke" {
  statement_id             = local.parser_url_invoke_statement_id
  function_name            = aws_lambda_function.parser.function_name
  action                   = "lambda:InvokeFunction"
  principal                = "*"
  invoked_via_function_url = true
}
