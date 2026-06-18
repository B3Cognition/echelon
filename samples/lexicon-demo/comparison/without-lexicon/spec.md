# Temperature Converter CLI — Specification

> A command-line tool that converts temperature values between Celsius and Fahrenheit. The user provides a numeric value and a target unit; the tool outputs the converted result rounded to one decimal place. The tool rejects non-numeric input and unrecognized target units with clear error messages.

## User Scenarios & Testing

### Scenario 1: Convert Celsius to Fahrenheit

**As a** user of the temperature converter,
**I want to** provide a Celsius value and request conversion to Fahrenheit,
**So that** I obtain the equivalent temperature in the Fahrenheit scale.

#### Acceptance Criteria

- **AC-001**: Given a numeric value of 100 and a target unit of Fahrenheit, when the user invokes the tool, then the output displays 212.0.
- **AC-002**: Given a numeric value of 0 and a target unit of Fahrenheit, when the user invokes the tool, then the output displays 32.0.
- **AC-003**: Given a numeric value of -40 and a target unit of Fahrenheit, when the user invokes the tool, then the output displays -40.0.

### Scenario 2: Convert Fahrenheit to Celsius

**As a** user of the temperature converter,
**I want to** provide a Fahrenheit value and request conversion to Celsius,
**So that** I obtain the equivalent temperature in the Celsius scale.

#### Acceptance Criteria

- **AC-004**: Given a numeric value of 212 and a target unit of Celsius, when the user invokes the tool, then the output displays 100.0.
- **AC-005**: Given a numeric value of 32 and a target unit of Celsius, when the user invokes the tool, then the output displays 0.0.
- **AC-006**: Given a numeric value of 98.6 and a target unit of Celsius, when the user invokes the tool, then the output displays 37.0.

### Scenario 3: Handle Invalid Input

**As a** user of the temperature converter,
**I want to** receive a clear error message when I provide invalid input,
**So that** I understand what went wrong and can correct my invocation.

#### Acceptance Criteria

- **AC-007**: Given a non-numeric value such as "abc" and a target unit of Fahrenheit, when the user invokes the tool, then the tool displays an error message indicating the value is not a valid number, and the tool exits with a non-zero status code.
- **AC-008**: Given a numeric value of 100 and an unrecognized target unit such as "Kelvin", when the user invokes the tool, then the tool displays an error message indicating the target unit is not supported, and the tool exits with a non-zero status code.
- **AC-009**: Given no arguments are provided, when the user invokes the tool, then the tool displays a usage message describing the expected arguments.

### Scenario 4: Rounding Behavior

**As a** user of the temperature converter,
**I want to** see converted values rounded to exactly one decimal place,
**So that** I get a consistently formatted result without excessive precision.

#### Acceptance Criteria

- **AC-010**: Given a numeric value of 33 and a target unit of Celsius, when the user invokes the tool, then the output displays 0.6 (the precise result 0.5556 rounded to one decimal).
- **AC-011**: Given a numeric value of 37.777 and a target unit of Fahrenheit, when the user invokes the tool, then the output displays 99.999 rounded to one decimal as 100.0.

## Functional Requirements

### Temperature Conversion

- **FR-001**: The system SHALL accept a numeric temperature value and a target unit as input arguments from the command line.
  - **User Story:** Scenario 1, Scenario 2
  - **Priority:** MVP
- **FR-002**: When the target unit is Fahrenheit, the system SHALL convert the input value from Celsius to Fahrenheit using the standard conversion formula and display the result.
  - **User Story:** Scenario 1
  - **Priority:** MVP
- **FR-003**: When the target unit is Celsius, the system SHALL convert the input value from Fahrenheit to Celsius using the standard conversion formula and display the result.
  - **User Story:** Scenario 2
  - **Priority:** MVP
- **FR-004**: The system SHALL round all converted output values to exactly one decimal place before displaying them.
  - **User Story:** Scenario 4
  - **Priority:** MVP

### Input Validation and Error Handling

- **FR-005**: The system SHALL reject any input value that is not a valid number and display an error message that identifies the invalid input, then exit with a non-zero status code.
  - **User Story:** Scenario 3
  - **Priority:** MVP
- **FR-006**: The system SHALL reject any target unit that is not one of the supported units (Celsius, Fahrenheit) and display an error message that lists the supported units, then exit with a non-zero status code.
  - **User Story:** Scenario 3
  - **Priority:** MVP
- **FR-007**: When the user provides insufficient arguments, the system SHALL display a usage message describing the expected input format and exit with a non-zero status code.
  - **User Story:** Scenario 3
  - **Priority:** MVP

## Non-Functional Requirements

- **NFR-001**: The tool SHALL produce output within 1 second of invocation under normal operating conditions.
  - **Category:** Performance
  - **Measurable Target:** Response time less than 1 second for any single conversion
- **NFR-002**: The tool SHALL operate without requiring network connectivity or external service dependencies.
  - **Category:** Reliability
  - **Measurable Target:** 100% of conversions succeed in an offline environment

## Key Entities

### Temperature Value
- **Attributes:** numeric magnitude, source unit (implied by context)
- **Relationships:** input to exactly one Conversion Operation
- **Lifecycle:** provided as input, validated, consumed by conversion
- **Constraints:** must be a valid numeric value; no inherent range restriction

### Target Unit
- **Attributes:** unit identifier (Celsius or Fahrenheit)
- **Relationships:** determines which conversion formula is applied
- **Lifecycle:** provided as input, validated against supported set
- **Constraints:** must be one of the recognized supported units

### Conversion Result
- **Attributes:** numeric magnitude rounded to one decimal place
- **Relationships:** produced by exactly one Conversion Operation, displayed to the user
- **Lifecycle:** computed, rounded, displayed
- **Constraints:** always rounded to exactly one decimal place

## Success Criteria

### MVP Success
- [ ] All seven functional requirements pass acceptance testing
- [ ] Celsius-to-Fahrenheit conversions produce correct results for known reference values (0C=32F, 100C=212F, -40C=-40F)
- [ ] Fahrenheit-to-Celsius conversions produce correct results for known reference values (32F=0C, 212F=100C, 98.6F=37C)
- [ ] Invalid numeric input is rejected with a descriptive error
- [ ] Unsupported target units are rejected with a descriptive error

## Scope

### In Scope (MVP)
- Celsius to Fahrenheit conversion
- Fahrenheit to Celsius conversion
- Rounding to one decimal place
- Input validation for non-numeric values
- Error handling for unsupported target units
- Usage message when arguments are missing

### Explicitly Out of Scope
- Kelvin or Rankine conversions — only Celsius and Fahrenheit are supported in this version
- Interactive mode or REPL — the tool processes a single conversion per invocation
- Batch file processing — the tool accepts exactly one value per invocation
- Configuration files or persistent settings — the tool is stateless

## Open Questions

| ID | Question | Impact | Source |
|----|----------|--------|--------|
| OQ-001 | Should the tool accept unit abbreviations (C, F) in addition to full names (Celsius, Fahrenheit)? | Affects FR-001 and FR-006 input parsing | User requirement ambiguity |
| OQ-002 | Should the output include the unit label (e.g., "100.0 F") or just the numeric value (e.g., "100.0")? | Affects output format of FR-002, FR-003 | User requirement ambiguity |

## Assumptions in Effect

| ID | Assumption | Status | Requirements Affected |
|----|-----------|--------|----------------------|
| A-001 | The tool operates as a single-invocation command-line utility, not a persistent service | Unvalidated | All FRs |
| A-002 | Standard arithmetic conversion formulas (F = C * 9/5 + 32, C = (F - 32) * 5/9) are the expected formulas | Validated | FR-002, FR-003 |
| A-003 | The tool reads input from command-line arguments, not from standard input | Unvalidated | FR-001, FR-007 |
