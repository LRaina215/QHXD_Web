// Copyright 2026 Qionghai Xindong Robot Team
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include <curl/curl.h>

#include <fcntl.h>
#include <sys/stat.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cinttypes>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/imu.hpp"

namespace
{

int64_t steadyNowMs()
{
  return std::chrono::duration_cast<std::chrono::milliseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
}

std::string jsonEscape(const std::string & value)
{
  std::ostringstream output;
  for (const unsigned char ch : value) {
    switch (ch) {
      case '"': output << "\\\""; break;
      case '\\': output << "\\\\"; break;
      case '\b': output << "\\b"; break;
      case '\f': output << "\\f"; break;
      case '\n': output << "\\n"; break;
      case '\r': output << "\\r"; break;
      case '\t': output << "\\t"; break;
      default:
        if (ch < 0x20U) {
          output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                 << static_cast<int>(ch) << std::dec;
        } else {
          output << static_cast<char>(ch);
        }
    }
  }
  return output.str();
}

std::string timestampIso(int32_t sec, uint32_t nanosec)
{
  if (sec <= 0) {
    const auto now = std::chrono::system_clock::now();
    sec = static_cast<int32_t>(
      std::chrono::duration_cast<std::chrono::seconds>(now.time_since_epoch()).count());
    nanosec = static_cast<uint32_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count() %
      1000000000LL);
  }
  const std::time_t epoch = static_cast<std::time_t>(sec);
  std::tm utc_time {};
  gmtime_r(&epoch, &utc_time);
  char date_buffer[32] {};
  std::strftime(date_buffer, sizeof(date_buffer), "%Y-%m-%dT%H:%M:%S", &utc_time);
  std::ostringstream output;
  output << date_buffer << '.' << std::setw(9) << std::setfill('0') << nanosec << 'Z';
  return output.str();
}

void quaternionToEulerDegrees(
  double x, double y, double z, double w, double & yaw, double & pitch, double & roll)
{
  const double sinr_cosp = 2.0 * (w * x + y * z);
  const double cosr_cosp = 1.0 - 2.0 * (x * x + y * y);
  roll = std::atan2(sinr_cosp, cosr_cosp);

  const double sinp = 2.0 * (w * y - z * x);
  pitch = std::abs(sinp) >= 1.0 ? std::copysign(M_PI / 2.0, sinp) : std::asin(sinp);

  const double siny_cosp = 2.0 * (w * z + x * y);
  const double cosy_cosp = 1.0 - 2.0 * (y * y + z * z);
  yaw = std::atan2(siny_cosp, cosy_cosp);

  constexpr double radians_to_degrees = 180.0 / M_PI;
  yaw *= radians_to_degrees;
  pitch *= radians_to_degrees;
  roll *= radians_to_degrees;
}

std::string imuPayload(const sensor_msgs::msg::Imu & msg, const std::string & source)
{
  double yaw = 0.0;
  double pitch = 0.0;
  double roll = 0.0;
  quaternionToEulerDegrees(
    msg.orientation.x, msg.orientation.y, msg.orientation.z, msg.orientation.w,
    yaw, pitch, roll);

  const std::string timestamp = timestampIso(msg.header.stamp.sec, msg.header.stamp.nanosec);
  const std::string updated_at = timestampIso(0, 0);
  const std::string frame_id = msg.header.frame_id.empty() ? "imu_link" : msg.header.frame_id;

  std::ostringstream body;
  body << std::setprecision(12)
       << "{\"source\":\"" << jsonEscape(source) << "\","
       << "\"updated_at\":\"" << updated_at << "\","
       << "\"imu\":{"
       << "\"frame_id\":\"" << jsonEscape(frame_id) << "\","
       << "\"timestamp\":\"" << timestamp << "\","
       << "\"orientation\":{"
       << "\"x\":" << msg.orientation.x << ",\"y\":" << msg.orientation.y
       << ",\"z\":" << msg.orientation.z << ",\"w\":" << msg.orientation.w << "},"
       << "\"euler_deg\":{"
       << "\"yaw\":" << yaw << ",\"pitch\":" << pitch << ",\"roll\":" << roll << "},"
       << "\"angular_velocity\":{"
       << "\"x\":" << msg.angular_velocity.x << ",\"y\":" << msg.angular_velocity.y
       << ",\"z\":" << msg.angular_velocity.z << "},"
       << "\"linear_acceleration\":{"
       << "\"x\":" << msg.linear_acceleration.x << ",\"y\":" << msg.linear_acceleration.y
       << ",\"z\":" << msg.linear_acceleration.z << "}}}";
  return body.str();
}

size_t appendResponse(char * data, size_t size, size_t count, void * output)
{
  const size_t bytes = size * count;
  static_cast<std::string *>(output)->append(data, bytes);
  return bytes;
}

}  // namespace

class ImuBackendBridge : public rclcpp::Node
{
public:
  ImuBackendBridge()
  : Node("qhxd_imu_backend_bridge")
  {
    topic_ = declare_parameter<std::string>("topic", "/serial/imu");
    backend_url_ = declare_parameter<std::string>("backend_url", "http://127.0.0.1:8000");
    source_ = declare_parameter<std::string>("source", "rk3588_cboard_ros2");
    heartbeat_file_ = declare_parameter<std::string>(
      "heartbeat_file", ".runtime/ros2_imu_bridge.heartbeat");
    rate_hz_ = std::max(0.1, declare_parameter<double>("rate_hz", 20.0));
    timeout_ms_ = std::max<int64_t>(
      100, declare_parameter<int64_t>("timeout_ms", 1000));
    mock_probe_interval_ms_ = std::max<int64_t>(
      500, declare_parameter<int64_t>("mock_probe_interval_ms", 2000));
    log_interval_ms_ = std::max<int64_t>(
      1000, declare_parameter<int64_t>("log_interval_ms", 5000));
    endpoint_ = backend_url_;
    while (!endpoint_.empty() && endpoint_.back() == '/') {
      endpoint_.pop_back();
    }
    endpoint_ += "/api/internal/nuc/imu";
    sample_interval_ms_ = std::max<int64_t>(1, static_cast<int64_t>(1000.0 / rate_hz_));

    auto qos = rclcpp::SensorDataQoS().keep_last(1);
    subscription_ = create_subscription<sensor_msgs::msg::Imu>(
      topic_, qos,
      std::bind(&ImuBackendBridge::onImu, this, std::placeholders::_1));

    const auto timer_period = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::duration<double>(1.0 / rate_hz_));
    submit_timer_ = create_wall_timer(
      timer_period, std::bind(&ImuBackendBridge::queueLatest, this));
    stale_timer_ = create_wall_timer(
      std::chrono::seconds(5), std::bind(&ImuBackendBridge::checkStale, this));
    worker_ = std::thread(&ImuBackendBridge::workerLoop, this);

    RCLCPP_INFO(
      get_logger(), "C++ bridge %s -> %s, source=%s, rate=%.1f Hz",
      topic_.c_str(), endpoint_.c_str(), source_.c_str(), rate_hz_);
  }

  ~ImuBackendBridge() override
  {
    stop_.store(true);
    worker_cv_.notify_all();
    if (worker_.joinable()) {
      worker_.join();
    }
  }

private:
  void onImu(const sensor_msgs::msg::Imu::SharedPtr msg)
  {
    const int64_t now = steadyNowMs();
    last_message_ms_.store(now, std::memory_order_relaxed);
    touchHeartbeat(now);

    int64_t previous = last_sampled_ms_.load(std::memory_order_relaxed);
    if (now - previous < sample_interval_ms_ ||
      !last_sampled_ms_.compare_exchange_strong(previous, now, std::memory_order_relaxed))
    {
      return;
    }

    std::lock_guard<std::mutex> lock(latest_mutex_);
    latest_ = *msg;
    latest_version_++;
    has_latest_ = true;
  }

  void touchHeartbeat(int64_t now)
  {
    int64_t previous = last_heartbeat_ms_.load(std::memory_order_relaxed);
    if (now - previous < 1000 ||
      !last_heartbeat_ms_.compare_exchange_strong(
        previous, now, std::memory_order_relaxed))
    {
      return;
    }
    if (utimensat(AT_FDCWD, heartbeat_file_.c_str(), nullptr, 0) != 0) {
      std::ofstream create_file(heartbeat_file_, std::ios::app);
      if (!create_file && shouldLog(now)) {
        RCLCPP_WARN(get_logger(), "Failed to update IMU heartbeat: %s", heartbeat_file_.c_str());
      }
    }
  }

  void queueLatest()
  {
    const int64_t now = steadyNowMs();
    if (now < backoff_until_ms_.load(std::memory_order_relaxed)) {
      return;
    }

    sensor_msgs::msg::Imu sample;
    uint64_t version = 0;
    {
      std::lock_guard<std::mutex> lock(latest_mutex_);
      if (!has_latest_ || latest_version_ == last_enqueued_version_) {
        return;
      }
      sample = latest_;
      version = latest_version_;
      last_enqueued_version_ = version;
    }
    {
      std::lock_guard<std::mutex> lock(worker_mutex_);
      pending_ = sample;
      pending_version_ = version;
      has_pending_ = true;
    }
    worker_cv_.notify_one();
  }

  void workerLoop()
  {
    while (!stop_.load()) {
      sensor_msgs::msg::Imu sample;
      {
        std::unique_lock<std::mutex> lock(worker_mutex_);
        worker_cv_.wait(lock, [this]() {return stop_.load() || has_pending_;});
        if (stop_.load()) {
          return;
        }
        sample = pending_;
        has_pending_ = false;
      }
      postSample(sample);
    }
  }

  void postSample(const sensor_msgs::msg::Imu & sample)
  {
    CURL * curl = curl_easy_init();
    if (curl == nullptr) {
      logFailure("curl_easy_init failed");
      return;
    }

    const std::string body = imuPayload(sample, source_);
    std::string response;
    struct curl_slist * headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    curl_easy_setopt(curl, CURLOPT_URL, endpoint_.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(
      curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));  // NOLINT(runtime/int)
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, timeout_ms_);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, timeout_ms_);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, appendResponse);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);

    const CURLcode result = curl_easy_perform(curl);
    long status = 0;  // NOLINT(runtime/int)
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (result != CURLE_OK || status < 200 || status >= 300) {
      std::ostringstream detail;
      detail << "HTTP post failed: curl=" << curl_easy_strerror(result) << ", status=" << status;
      logFailure(detail.str());
      return;
    }

    const bool accepted = response.find("\"accepted\":true") != std::string::npos &&
      response.find("\"imu_updated\":true") != std::string::npos;
    if (accepted) {
      const uint64_t count = accepted_count_.fetch_add(1) + 1;
      const int64_t now = steadyNowMs();
      if (shouldLog(now)) {
        RCLCPP_INFO(get_logger(), "Accepted IMU samples: %" PRIu64, count);
      }
      return;
    }

    backoff_until_ms_.store(steadyNowMs() + mock_probe_interval_ms_, std::memory_order_relaxed);
    const int64_t now = steadyNowMs();
    if (shouldLog(now)) {
      if (
        response.find("Mock") != std::string::npos ||
        response.find("mock") != std::string::npos)
      {
        RCLCPP_WARN(
          get_logger(), "Backend is in Mock mode; pausing IMU posts for %.1f s",
          mock_probe_interval_ms_ / 1000.0);
      } else {
        RCLCPP_WARN(get_logger(), "Backend rejected IMU sample; response=%s", response.c_str());
      }
    }
  }

  void logFailure(const std::string & detail)
  {
    error_count_.fetch_add(1);
    const int64_t now = steadyNowMs();
    if (shouldLog(now)) {
      RCLCPP_WARN(
        get_logger(), "%s; errors=%" PRIu64, detail.c_str(), error_count_.load());
    }
  }

  bool shouldLog(int64_t now)
  {
    int64_t previous = last_log_ms_.load(std::memory_order_relaxed);
    while (now - previous >= log_interval_ms_) {
      if (last_log_ms_.compare_exchange_weak(previous, now, std::memory_order_relaxed)) {
        return true;
      }
    }
    return false;
  }

  void checkStale()
  {
    const int64_t last = last_message_ms_.load(std::memory_order_relaxed);
    const int64_t now = steadyNowMs();
    if (last <= 0 && shouldLog(now)) {
      RCLCPP_WARN(get_logger(), "Waiting for IMU messages on %s", topic_.c_str());
    } else if (last > 0 && now - last > 5000 && shouldLog(now)) {
      RCLCPP_WARN(get_logger(), "No IMU message received for %.1f s", (now - last) / 1000.0);
    }
  }

  std::string topic_;
  std::string backend_url_;
  std::string endpoint_;
  std::string source_;
  std::string heartbeat_file_;
  double rate_hz_ = 20.0;
  int64_t timeout_ms_ = 1000;
  int64_t mock_probe_interval_ms_ = 2000;
  int64_t log_interval_ms_ = 5000;
  int64_t sample_interval_ms_ = 50;

  rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr subscription_;
  rclcpp::TimerBase::SharedPtr submit_timer_;
  rclcpp::TimerBase::SharedPtr stale_timer_;

  std::mutex latest_mutex_;
  sensor_msgs::msg::Imu latest_;
  bool has_latest_ = false;
  uint64_t latest_version_ = 0;
  uint64_t last_enqueued_version_ = 0;

  std::mutex worker_mutex_;
  std::condition_variable worker_cv_;
  sensor_msgs::msg::Imu pending_;
  uint64_t pending_version_ = 0;
  bool has_pending_ = false;
  std::thread worker_;

  std::atomic<bool> stop_ {false};
  std::atomic<int64_t> last_message_ms_ {0};
  std::atomic<int64_t> last_sampled_ms_ {0};
  std::atomic<int64_t> last_heartbeat_ms_ {0};
  std::atomic<int64_t> last_log_ms_ {0};
  std::atomic<int64_t> backoff_until_ms_ {0};
  std::atomic<uint64_t> accepted_count_ {0};
  std::atomic<uint64_t> error_count_ {0};
};

int main(int argc, char ** argv)
{
  curl_global_init(CURL_GLOBAL_DEFAULT);
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ImuBackendBridge>());
  rclcpp::shutdown();
  curl_global_cleanup();
  return 0;
}
