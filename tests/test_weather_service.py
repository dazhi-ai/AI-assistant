import unittest

from plugins.weather_service import WeatherService


class WeatherServiceLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WeatherService(api_key="demo-key")
        self.minutely_data = {
            "summary": "35分钟后雨就停了",
            "minutely": [
                {"fxTime": "2026-03-28T18:50+08:00", "precip": "0.00", "type": "rain"},
                {"fxTime": "2026-03-28T18:55+08:00", "precip": "0.15", "type": "rain"},
                {"fxTime": "2026-03-28T19:00+08:00", "precip": "0.23", "type": "rain"},
                {"fxTime": "2026-03-28T19:05+08:00", "precip": "0.08", "type": "rain"},
                {"fxTime": "2026-03-28T19:10+08:00", "precip": "0.00", "type": "rain"},
            ],
        }
        self.hourly_data = [
            {"fxTime": "2026-03-28T18:00+08:00", "text": "多云", "pop": "10", "precip": "0.0"},
            {"fxTime": "2026-03-28T19:00+08:00", "text": "小雨", "pop": "80", "precip": "0.8"},
            {"fxTime": "2026-03-28T20:00+08:00", "text": "中雨", "pop": "90", "precip": "1.6"},
            {"fxTime": "2026-03-28T21:00+08:00", "text": "阴", "pop": "20", "precip": "0.0"},
        ]

    def test_minutely_summary_contains_start_and_stop_time(self) -> None:
        summary = self.service._build_minutely_summary(self.minutely_data)
        self.assertIn("18:55", summary)
        self.assertIn("19:05", summary)

    def test_analyze_minutely_query_reports_stop_time(self) -> None:
        answer = self.service._analyze_minutely_query(self.minutely_data, "雨什么时候停")
        self.assertIn("19:05", answer)
        self.assertIn("停", answer)

    def test_analyze_minutely_query_reports_specific_time_rain(self) -> None:
        answer = self.service._analyze_minutely_query(self.minutely_data, "18点58分会不会下雨")
        self.assertIn("19:00", answer)
        self.assertIn("降水", answer)

    def test_analyze_hourly_window_reports_evening_rain(self) -> None:
        answer = self.service._analyze_hourly_window(self.hourly_data, "今晚会不会下雨")
        self.assertIn("今晚", answer)
        self.assertIn("19:00", answer)
        self.assertIn("20:00", answer)


if __name__ == "__main__":
    unittest.main()
