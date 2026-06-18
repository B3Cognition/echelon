ARTIFACT: SPEC
TITLE: Temperature Converter CLI

REQ: TC-001
GIVEN: a temperature_value in Celsius and a target_unit of Fahrenheit
WHEN: the user invokes the Temperature_Converter with the temperature_value and the target_unit
THEN: the Temperature_Converter MUST compute the converted_value using the Celsius-to-Fahrenheit formula
OUTPUT: the converted_value is printed to standard_output rounded to one decimal_place
CONSTRAINT: decimal_place = 1

REQ: TC-002
GIVEN: a temperature_value in Fahrenheit and a target_unit of Celsius
WHEN: the user invokes the Temperature_Converter with the temperature_value and the target_unit
THEN: the Temperature_Converter MUST compute the converted_value using the Fahrenheit-to-Celsius formula
OUTPUT: the converted_value is printed to standard_output rounded to one decimal_place
CONSTRAINT: decimal_place = 1

REQ: TC-003
GIVEN: a temperature_value that is a valid number
WHEN: the Temperature_Converter computes the converted_value
THEN: the Temperature_Converter MUST round the converted_value to exactly one decimal_place
OUTPUT: the converted_value displayed on standard_output contains exactly one digit after the decimal point
CONSTRAINT: decimal_place = 1

REQ: TC-004
GIVEN: an input_argument that is not a valid number
WHEN: the user invokes the Temperature_Converter with the non-numeric input_argument
THEN: the Temperature_Converter MUST reject the input_argument and print an error_message
OUTPUT: an error_message is printed and the exit_code is non-zero
CONSTRAINT: exit_code != 0

REQ: TC-005
GIVEN: a target_unit that is neither Celsius nor Fahrenheit
WHEN: the user invokes the Temperature_Converter with the unrecognized target_unit
THEN: the Temperature_Converter MUST reject the target_unit and print an error_message
OUTPUT: an error_message is printed and the exit_code is non-zero
CONSTRAINT: exit_code != 0

REQ: TC-006
GIVEN: a valid temperature_value and a recognized target_unit
WHEN: the Temperature_Converter completes the conversion without error
THEN: the Temperature_Converter MUST terminate with an exit_code of zero
OUTPUT: the exit_code is zero and the converted_value appears on standard_output
CONSTRAINT: exit_code = 0

REQ: TC-007
GIVEN: a temperature_value of zero in Celsius and a target_unit of Fahrenheit
WHEN: the user invokes the Temperature_Converter
THEN: the Temperature_Converter MUST return a converted_value of 32.0
OUTPUT: the standard_output displays 32.0

AC: TC-AC-001
GIVEN: a temperature_value of 100 in Celsius and a target_unit of Fahrenheit
WHEN: the user invokes the Temperature_Converter
THEN: the standard_output displays a converted_value of 212.0 and the exit_code is zero

AC: TC-AC-002
GIVEN: a temperature_value of 212 in Fahrenheit and a target_unit of Celsius
WHEN: the user invokes the Temperature_Converter
THEN: the standard_output displays a converted_value of 100.0 and the exit_code is zero

AC: TC-AC-003
GIVEN: an input_argument of the text abc and a target_unit of Fahrenheit
WHEN: the user invokes the Temperature_Converter
THEN: an error_message is printed and the exit_code is non-zero

ERROR: TC-ERR-001
WHEN: the input_argument is not a numeric temperature_value
THEN: reject the input_argument and print an error_message indicating the value is not a number
ERROR_CODE: INVALID_NUMBER

ERROR: TC-ERR-002
WHEN: the target_unit is not Celsius or Fahrenheit
THEN: reject the target_unit and print an error_message indicating the unit is not recognized
ERROR_CODE: UNKNOWN_UNIT
