import os
import sys
import unittest

# Add parent directory to path to import main
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import find_course_info


class TestCourseSelection(unittest.TestCase):
    def setUp(self):
        self.courses = [
            # Case 1: Multiple classes for same course
            {"haksuNo": "COE8042", "suupNo": "30016", "gwamokNm": "Probability and Statistics (Class A)"},
            {"haksuNo": "COE8042", "suupNo": "33846", "gwamokNm": "Probability and Statistics (Class B)"},
            
            # Case 2: Single class course
            {"haksuNo": "COE9013", "suupNo": "30030", "gwamokNm": "Probability and Statistics (English)"},
            
            # Case 3: Another course
            {"haksuNo": "CIV9101", "suupNo": "30482", "gwamokNm": "Civil Engineering Statistics"}
        ]

    def test_string_input_compatibility(self):
        """Test backward compatibility with string input"""
        # Should return the first matching course
        result = find_course_info(self.courses, "COE8042")
        self.assertIsNotNone(result)
        self.assertEqual(result["suupNo"], "30016")

    def test_dict_input_haksu_only(self):
        """Test dictionary input with only haksuNo"""
        # Should behave like string input
        result = find_course_info(self.courses, {"haksuNo": "COE8042"})
        self.assertIsNotNone(result)
        self.assertEqual(result["suupNo"], "30016")

    def test_dict_input_specific_class(self):
        """Test dictionary input with haksuNo and suupNo"""
        # Should return the specific class (Class B)
        result = find_course_info(self.courses, {"haksuNo": "COE8042", "suupNo": "33846"})
        self.assertIsNotNone(result)
        self.assertEqual(result["suupNo"], "33846")
        self.assertEqual(result["gwamokNm"], "Probability and Statistics (Class B)")

    def test_dict_input_first_class(self):
        """Test dictionary input with haksuNo and suupNo for the first class"""
        # Should return the specific class (Class A)
        result = find_course_info(self.courses, {"haksuNo": "COE8042", "suupNo": "30016"})
        self.assertIsNotNone(result)
        self.assertEqual(result["suupNo"], "30016")

    def test_no_match_haksu(self):
        """Test no match for haksuNo"""
        result = find_course_info(self.courses, "INVALID")
        self.assertIsNone(result)

    def test_no_match_suup(self):
        """Test correct haksuNo but wrong suupNo"""
        result = find_course_info(self.courses, {"haksuNo": "COE8042", "suupNo": "99999"})
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
