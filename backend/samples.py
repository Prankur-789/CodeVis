"""codevis.samples - built-in example programs offered in the editor."""

SAMPLES = [
    {
        "id": "python-sum-evens",
        "language": "python",
        "title": "Sum of Even Numbers",
        "description": "Loops through a list and accumulates the even numbers.",
        "code": (
            "numbers = [1, 2, 3, 4, 5]\n"
            "total = 0\n"
            "\n"
            "for number in numbers:\n"
            "    if number % 2 == 0:\n"
            "        total = total + number\n"
            "\n"
            'print("Sum =", total)\n'
        ),
    },
    {
        "id": "python-fizzbuzz",
        "language": "python",
        "title": "FizzBuzz",
        "description": "Classic interview warm-up combining loops and branching.",
        "code": (
            "for i in range(1, 16):\n"
            "    if i % 15 == 0:\n"
            '        print("FizzBuzz")\n'
            "    elif i % 3 == 0:\n"
            '        print("Fizz")\n'
            "    elif i % 5 == 0:\n"
            '        print("Buzz")\n'
            "    else:\n"
            "        print(i)\n"
        ),
    },
    {
        "id": "c-factorial",
        "language": "c",
        "title": "Factorial",
        "description": "Computes n! using a for loop.",
        "code": (
            "#include <stdio.h>\n"
            "\n"
            "int main() {\n"
            "    int n = 5;\n"
            "    int factorial = 1;\n"
            "\n"
            "    for (int i = 1; i <= n; i++) {\n"
            "        factorial = factorial * i;\n"
            "    }\n"
            "\n"
            '    printf("Factorial = %d\\n", factorial);\n'
            "\n"
            "    return 0;\n"
            "}\n"
        ),
    },
    {
        "id": "c-fibonacci",
        "language": "c",
        "title": "Fibonacci Sequence",
        "description": "Prints the first n Fibonacci numbers using a while loop.",
        "code": (
            "#include <stdio.h>\n"
            "\n"
            "int main() {\n"
            "    int n = 10;\n"
            "    int a = 0, b = 1;\n"
            "    int i = 0;\n"
            "\n"
            "    while (i < n) {\n"
            '        printf("%d ", a);\n'
            "        int next = a + b;\n"
            "        a = b;\n"
            "        b = next;\n"
            "        i++;\n"
            "    }\n"
            "\n"
            "    return 0;\n"
            "}\n"
        ),
    },
    {
        "id": "cpp-prime-check",
        "language": "cpp",
        "title": "Prime Number Check",
        "description": "Determines whether a number is prime by counting its divisors.",
        "code": (
            "#include <iostream>\n"
            "using namespace std;\n"
            "\n"
            "int main() {\n"
            "    int number = 17;\n"
            "    int count = 0;\n"
            "\n"
            "    for (int i = 1; i <= number; i++) {\n"
            "        if (number % i == 0) {\n"
            "            count++;\n"
            "        }\n"
            "    }\n"
            "\n"
            "    if (count == 2) {\n"
            '        cout << "Prime Number" << endl;\n'
            "    } else {\n"
            '        cout << "Not a Prime Number" << endl;\n'
            "    }\n"
            "\n"
            "    return 0;\n"
            "}\n"
        ),
    },
    {
        "id": "cpp-array-max",
        "language": "cpp",
        "title": "Find Maximum in Array",
        "description": "Scans an array while tracking the largest value seen so far.",
        "code": (
            "#include <iostream>\n"
            "using namespace std;\n"
            "\n"
            "int main() {\n"
            "    int values[5] = {12, 45, 7, 89, 34};\n"
            "    int maxVal = values[0];\n"
            "\n"
            "    for (int i = 1; i < 5; i++) {\n"
            "        if (values[i] > maxVal) {\n"
            "            maxVal = values[i];\n"
            "        }\n"
            "    }\n"
            "\n"
            '    cout << "Maximum = " << maxVal << endl;\n'
            "    return 0;\n"
            "}\n"
        ),
    },
]
