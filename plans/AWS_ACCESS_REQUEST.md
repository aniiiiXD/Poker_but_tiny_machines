# AWS access request for Stack Theory pilot

## Verified blocker

The existing `PassKarwado` IAM user authenticates to account `169970912263`. A non-mutating EC2 `RunInstances` dry run in Mumbai (`ap-south-1`) returned `UnauthorizedOperation`: no identity-based policy allows `ec2:RunInstances` on the instance resource. EC2 listing is also denied. The same launch dry run was denied in `us-east-1`. IAM policy simulation is denied, so these checks do not establish the complete permission set. Lambda and ECR can be listed, but listing alone does not establish permission to create resources.

## Request to the AWS administrator

Please create a **dedicated Stack Theory pilot host and deployment access** in account `169970912263`, preferably `ap-south-1`:

- One EC2 Linux instance with approximately 2 vCPUs and 8 GiB RAM, and an encrypted 30 GiB gp3 EBS volume. Confirm the current instance price and budget before launch; this is an initial sizing assumption, not a benchmark or spend estimate.
- An instance profile with AWS Systems Manager connectivity, e.g. the `AmazonSSMManagedInstanceCore` managed policy, and only additional artifact/log permissions actually needed by the pilot. Require IMDSv2. Keep secrets in a service designed for them, not in bot containers.
- A security group that exposes HTTPS only. Do not open SSH or Docker to the internet. A hostname under a domain you control is needed to issue a valid TLS certificate and route the Vercel `/api` rewrite to this API.
- A dedicated operator role, preferably with temporary credentials, that can `ec2:DescribeInstances` and use Systems Manager `StartSession` or a narrowly scoped `SendCommand` on **this tagged instance only**, using approved SSM documents. Session access allows administrative actions on the host and should be limited to trusted operators. Grant artifact upload or deployment access only if needed.
- For an automated self-provisioning role instead, scope EC2 instance, security-group, network and volume permissions to this environment, and grant `iam:PassRole` only for the approved Stack Theory instance role. Do not grant broad IAM administration or use shared root credentials. Exact resource ARNs, tags, VPC and chosen tooling need an administrator to define and validate the final policy.

This is enough to deploy the existing FastAPI + SQLite + Docker worker stack as a **controlled pilot** with Vercel hosting the frontend. It is not an isolation design for a public multi-tenant adversarial-code service: the existing application and workers need the separation, persistent data, monitoring and security review described in [AWS and Vercel deployment plan](AWS_VERCEL_ARCHITECTURE.md) before a public launch.

The checks above were read-only; no AWS resources were created or modified while preparing this request.
