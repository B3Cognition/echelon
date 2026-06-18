# Glossary -- Temperature Converter CLI (approved terms)

- **temperature_value**: the numeric quantity representing a temperature reading
- **target_unit**: the unit the user requests conversion into (Celsius or Fahrenheit)
- **converted_value**: the result of applying the conversion formula to a temperature_value
- **decimal_place**: a single digit position after the decimal point
- **Temperature_Converter**: the command-line tool that performs temperature conversion
- **input_argument**: a value passed to the command-line tool by the user
- **exit_code**: the numeric status returned by the command-line tool upon termination
- **error_message**: the textual description printed when the tool rejects an input_argument
- **standard_output**: the output stream where the converted_value is printed
- **INVALID_NUMBER**: error code emitted when the input_argument is not a numeric value
- **UNKNOWN_UNIT**: error code emitted when the target_unit is not a recognized unit
