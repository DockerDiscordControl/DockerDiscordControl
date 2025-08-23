#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test the Discord Modal amount validation logic
"""

import re

def validate_amount(raw_amount):
    """Test function to validate amount input (same logic as Discord Modal)"""
    if not raw_amount:
        return "", None
    
    # Check for negative signs first (reject negative numbers)
    if '-' in raw_amount:
        return "", f"⚠️ Invalid amount: '{raw_amount}' - negative amounts not allowed"
    else:
        # Remove any non-numeric characters except dots and commas
        cleaned_amount = re.sub(r'[^\d.,]', '', raw_amount)
        
        # Replace comma with dot for decimal separator
        cleaned_amount = cleaned_amount.replace(',', '.')
        
        # Validate numeric format
        try:
            numeric_value = float(cleaned_amount)
            if numeric_value > 0:
                # Format with $ prefix
                return f"${numeric_value:.2f}", None
            elif numeric_value == 0:
                # Invalid: zero
                return "", f"⚠️ Invalid amount: '{raw_amount}' - must be greater than 0"
            else:
                return "", f"⚠️ Invalid amount: '{raw_amount}' - please use only numbers"
        except ValueError:
            # Invalid: not a valid number
            return "", f"⚠️ Invalid amount: '{raw_amount}' - please use only numbers (e.g. 10.50)"

def test_validation():
    """Test various inputs"""
    test_cases = [
        # Valid inputs
        ("10", "$10.00"),
        ("10.50", "$10.50"),
        ("5,50", "$5.50"),  # European format
        ("100.99", "$100.99"),
        ("0.01", "$0.01"),
        
        # Invalid inputs that should be cleaned
        ("$10", "$10.00"),  # Remove $
        ("10€", "$10.00"),  # Remove €
        ("10 euro", "$10.00"),  # Remove text
        ("abc10def", "$10.00"),  # Remove letters
        
        # Invalid inputs that should fail
        ("0", "error"),  # Zero
        ("-5", "error"),  # Negative
        ("abc", "error"),  # No numbers
        ("", ""),  # Empty
    ]
    
    print("🧪 Testing Discord Modal Amount Validation")
    print("=" * 50)
    
    passed = 0
    total = len(test_cases)
    
    for input_val, expected in test_cases:
        result, error = validate_amount(input_val)
        
        if expected == "error":
            # Expect an error
            if error:
                print(f"✅ '{input_val}' → ERROR (expected)")
                passed += 1
            else:
                print(f"❌ '{input_val}' → '{result}' (expected error)")
        elif expected == "":
            # Expect empty result
            if not result and not error:
                print(f"✅ '{input_val}' → EMPTY (expected)")
                passed += 1
            else:
                print(f"❌ '{input_val}' → '{result}' or '{error}' (expected empty)")
        else:
            # Expect specific result
            if result == expected and not error:
                print(f"✅ '{input_val}' → '{result}' (expected)")
                passed += 1
            else:
                print(f"❌ '{input_val}' → '{result}' or '{error}' (expected '{expected}')")
    
    print(f"\n🎯 Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 All validation tests passed!")
    else:
        print("⚠️ Some tests failed")

if __name__ == "__main__":
    test_validation()