# Dolphin Flow - Repair Workflow

Version:
0.1

Status:
Workflow Design

Last Updated:
2026-08-05


# 1. Purpose

This document defines the Repair Workflow in Dolphin Flow.

The workflow manages the complete lifecycle of a device repair request from initial reception until final delivery to the customer.


# 2. Workflow Information


Workflow Name:

Repair Process


Workflow Code:

REPAIR-001


Initial Version:

1.0


Owner:

After-Sales Service Department


# 3. Workflow Objectives


The Repair Workflow must:


- Digitize repair operations
- Maintain complete device history
- Control department responsibilities
- Track SLA performance
- Preserve approvals and documents
- Provide customer communication


# 4. Workflow Participants


The workflow involves:


| Department | Responsibility |
|---|---|
| Administrative | Device reception and shipment |
| Support | Warranty evaluation and customer communication |
| Repair | Technical inspection and repair |
| Finance | Payment verification |
| Warehouse | Storage and delivery preparation |
| Management | Exception approval |


# 5. Workflow Overview


High-level process:

```
# Workflow Flow


1. Device Reception

↓

2. Information Registration

↓

3. Warranty Evaluation


IF Warranty Approved:

    Repair
    ↓
    Warehouse


IF Warranty Rejected:

    Estimate Cost
    ↓
    Customer Approval

    IF Customer Approved:

        Repair
        ↓
        Final Cost
        ↓
        Finance Verification
        ↓
        Warehouse

    ELSE:

        Close Request


↓

Shipping

↓

Completed
```



# 6. Workflow Stages


# Stage 01 - Device Reception


## Responsible Department

Administrative


## Description

Device enters the organization and is received.


## Required Information


Customer:

- Name
- Contact information
- Address


Device:

- Device type
- IMEI
- Serial number (if available)


Shipment:

- Postal information
- Customer notes


## Required Actions


- Create repair request
- Register device information
- Attach received documents


## Output


Workflow moves to:

Warranty Evaluation


## SLA


To be defined by organization.


---

# Stage 02 - Request Registration


## Responsible Department

Administrative


## Description

Complete repair request information.


## Required Data


- Problem description
- Customer reported issue
- Device condition


## Required Approval

Administrative confirmation


## Output


Request becomes active.


---

# Stage 03 - Warranty Evaluation


## Responsible Department

Support


## Description

Support team determines warranty status.


## Possible Results


## Warranty Approved


Path:
```
Repair Department
    |
    Warehouse
```    

## Warranty Rejected


Path:
```
Customer Cost Approval
    |
Repair
```



## Required Information


- Warranty decision
- Reason
- Reviewer
- Date


---

# Stage 04A - Warranty Repair


## Responsible Department

Repair


## Description

Device is repaired under warranty.


## Actions


- Technical inspection
- Repair operation
- Technical report


## Required Documents


- Repair report


## Output


Device moves to:

Warehouse


---

# Stage 04B - Customer Cost Approval


## Responsible Department

Support


## Description

Customer receives estimated repair cost.


## Possible Results


### Approved


Continue:
```
Repair

```



### Rejected


Process:

Closed according to policy.


### Waiting


Process remains pending.


## Required Information


- Estimated cost
- Customer response
- Communication history


---

# Stage 05 - Paid Repair


## Responsible Department

Repair


## Description

Technical repair after customer approval.


## Actions


- Diagnosis
- Repair
- Technical report


## Output


Return to Support for final cost.


---

# Stage 06 - Final Cost Confirmation


## Responsible Department

Support


## Description

Final repair cost is calculated and communicated.


## Required Information


- Final amount
- Customer notification
- Payment request


## Output


Waiting for payment confirmation.


---

# Stage 07 - Financial Verification


## Responsible Department

Finance


## Description

Finance confirms customer payment.


## Required Documents


- Payment document
- Financial confirmation


## Output


Device moves to warehouse.


---

# Stage 08 - Warehouse Processing


## Responsible Department

Warehouse


## Description

Warehouse receives repaired device.


## Required Actions


- Receive device
- Register warehouse receipt
- Update inventory status


## Required Documents


- Warehouse receipt


---

# Stage 09 - Customer Shipment


## Responsible Department

Administrative


## Description

Device is prepared and shipped to customer.


## Required Actions


- Confirm address
- Register shipping information
- Enter tracking number


## Required Documents


- Shipment document


---

# Stage 10 - Process Completion


## Completion Requirements


A repair request can be completed only when:


- All devices have final status
- Required documents exist
- Required approvals exist
- Shipment information is registered


# 7. Multi Device Handling


A single repair request may contain multiple devices.


Example:
```
Repair Request #10001

Customer:

Company A

Devices:

Device 01
IMEI: XXXXX

Device 02
IMEI: YYYYY

```


Each device must have:


- Independent repair status
- Independent history
- Independent technical information


The workflow belongs to the repair request, while device operations are tracked individually.


# 8. Device Repeat Repair Handling


A device may enter repair multiple times.


Identification:


Primary:

IMEI


Additional:

- Device serial number
- Internal device identifier


Previous repair records must never be overwritten.


Example:

```
Device IMEI XXXXX

Repair #1

Date: 2026-01-10

Repair #2

Date: 2026-08-05

```



# 9. Required Documents Matrix


| Stage | Document |
|---|---|
| Reception | Receiving Form |
| Repair | Technical Report |
| Finance | Payment Document |
| Warehouse | Warehouse Receipt |
| Shipping | Shipment Document |


# 10. SLA Integration


Each stage must define:


- Target duration
- Warning threshold
- Escalation rule


Example:
```
Warranty Evaluation

SLA:

24 Hours

Warning:

18 Hours

Escalation:

Support Manager

```


# 11. Notifications


Customer notifications:


- Device received
- Repair status update
- Cost approval request
- Payment confirmation
- Shipment information


Internal notifications:


- New task assigned
- SLA warning
- Approval required


# 12. Exception Handling


Exceptions require:


- Reason
- Authorized user
- Audit record


Examples:


- Manual status change
- Process bypass
- Data correction after approval


# 13. Related Documents


Workflow Engine Design:
```
docs/04-Workflow/Workflow-Engine-Design.md

```

SLA Design:
```
docs/04-Workflow/SLA-Design.md
```

Business Rules:
```
docs/02-Requirements/Business-Rules.md
```