#include <curl/curl.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <iomanip>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "geometry_msgs/msg/transform_stamped.hpp"
#include "nav_msgs/msg/occupancy_grid.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "nav_msgs/msg/path.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2/time.h"
#include "tf2_ros/buffer.h"
#include "tf2_ros/transform_listener.h"

namespace
{
size_t discardResponse(char * data, size_t size, size_t count, void *)
{
  (void)data;
  return size * count;
}

std::string jsonEscape(const std::string & value)
{
  std::ostringstream stream;
  for (const char character : value) {
    switch (character) {
      case '"': stream << "\\\""; break;
      case '\\': stream << "\\\\"; break;
      case '\n': stream << "\\n"; break;
      case '\r': stream << "\\r"; break;
      case '\t': stream << "\\t"; break;
      default: stream << character; break;
    }
  }
  return stream.str();
}

std::string utcTimestamp()
{
  const auto now = std::chrono::system_clock::now();
  const auto millis = std::chrono::duration_cast<std::chrono::milliseconds>(
    now.time_since_epoch()) % 1000;
  const std::time_t seconds = std::chrono::system_clock::to_time_t(now);
  std::tm utc{};
  gmtime_r(&seconds, &utc);
  std::ostringstream stream;
  stream << std::put_time(&utc, "%Y-%m-%dT%H:%M:%S") << '.'
         << std::setfill('0') << std::setw(3) << millis.count() << 'Z';
  return stream.str();
}

double quaternionYaw(double x, double y, double z, double w)
{
  return std::atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z));
}

uint64_t fnv1a(const nav_msgs::msg::OccupancyGrid & map)
{
  uint64_t hash = 1469598103934665603ULL;
  const auto mix = [&hash](const uint8_t byte) {
      hash ^= byte;
      hash *= 1099511628211ULL;
    };
  for (const auto value : map.data) {
    mix(static_cast<uint8_t>(value));
  }
  for (int shift = 0; shift < 32; shift += 8) {
    mix(static_cast<uint8_t>((map.info.width >> shift) & 0xff));
    mix(static_cast<uint8_t>((map.info.height >> shift) & 0xff));
  }
  return hash;
}

struct Point2D
{
  double x{0.0};
  double y{0.0};
};

struct Pose2D
{
  double x{0.0};
  double y{0.0};
  double yaw{0.0};
};
}  // namespace

class NavigationWebBridge : public rclcpp::Node
{
public:
  NavigationWebBridge()
  : Node("navigation_web_bridge"),
    tf_buffer_(get_clock()),
    tf_listener_(tf_buffer_)
  {
    backend_base_url_ = declare_parameter<std::string>("backend_base_url", "http://127.0.0.1:8000");
    map_topic_ = declare_parameter<std::string>("map_topic", "/map");
    global_path_topic_ = declare_parameter<std::string>("global_path_topic", "/plan");
    local_path_topic_ = declare_parameter<std::string>("local_path_topic", "/local_plan");
    odometry_topic_ = declare_parameter<std::string>("odometry_topic", "/odometry");
    map_frame_ = declare_parameter<std::string>("map_frame", "map");
    base_frame_ = declare_parameter<std::string>("base_frame", "base_link");
    map_id_ = declare_parameter<std::string>("map_id", "sentinel_map");
    state_rate_hz_ = std::max(1.0, declare_parameter<double>("state_rate_hz", 10.0));
    http_timeout_ms_ = static_cast<int>(
      std::max<int64_t>(100, declare_parameter<int64_t>("http_timeout_ms", 400)));
    max_global_path_points_ = static_cast<int>(
      std::max<int64_t>(2, declare_parameter<int64_t>("max_global_path_points", 400)));
    max_local_path_points_ = static_cast<int>(
      std::max<int64_t>(2, declare_parameter<int64_t>("max_local_path_points", 200)));

    const auto map_qos = rclcpp::QoS(rclcpp::KeepLast(1)).transient_local().reliable();
    map_subscription_ = create_subscription<nav_msgs::msg::OccupancyGrid>(
      map_topic_, map_qos,
      [this](nav_msgs::msg::OccupancyGrid::SharedPtr message) {
        std::lock_guard<std::mutex> lock(data_mutex_);
        pending_map_ = std::move(message);
      });
    global_path_subscription_ = create_subscription<nav_msgs::msg::Path>(
      global_path_topic_, rclcpp::QoS(5),
      [this](nav_msgs::msg::Path::SharedPtr message) {
        std::lock_guard<std::mutex> lock(data_mutex_);
        global_path_ = std::move(message);
      });
    local_path_subscription_ = create_subscription<nav_msgs::msg::Path>(
      local_path_topic_, rclcpp::QoS(5),
      [this](nav_msgs::msg::Path::SharedPtr message) {
        std::lock_guard<std::mutex> lock(data_mutex_);
        local_path_ = std::move(message);
        local_path_received_at_ = std::chrono::steady_clock::now();
        local_path_seen_ = true;
      });
    odometry_subscription_ = create_subscription<nav_msgs::msg::Odometry>(
      odometry_topic_, rclcpp::QoS(10),
      [this](nav_msgs::msg::Odometry::SharedPtr message) {
        std::lock_guard<std::mutex> lock(data_mutex_);
        odometry_ = std::move(message);
      });

    const auto interval = std::chrono::duration<double>(1.0 / state_rate_hz_);
    timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::milliseconds>(interval),
      [this]() {publishSnapshot();});

    RCLCPP_INFO(
      get_logger(), "Navigation web bridge ready: backend=%s rate=%.1fHz map=%s pose=%s->%s",
      backend_base_url_.c_str(), state_rate_hz_, map_topic_.c_str(), map_frame_.c_str(),
      base_frame_.c_str());
  }

private:
  bool postJson(const std::string & path, const std::string & body)
  {
    CURL * curl = curl_easy_init();
    if (curl == nullptr) {
      return false;
    }
    struct curl_slist * headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    const std::string url = backend_base_url_ + path;
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 100L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, static_cast<long>(http_timeout_ms_));
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_NOPROXY, "*");
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, discardResponse);
    long status = 0;
    const CURLcode result = curl_easy_perform(curl);
    if (result == CURLE_OK) {
      curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    }
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    return result == CURLE_OK && status >= 200 && status < 300;
  }

  void publishSnapshot()
  {
    nav_msgs::msg::OccupancyGrid::SharedPtr map;
    nav_msgs::msg::Path::SharedPtr global_path;
    nav_msgs::msg::Path::SharedPtr local_path;
    nav_msgs::msg::Odometry::SharedPtr odometry;
    {
      std::lock_guard<std::mutex> lock(data_mutex_);
      if (local_path_seen_ &&
        std::chrono::steady_clock::now() - local_path_received_at_ > std::chrono::seconds(1))
      {
        local_path_.reset();
        global_path_.reset();
        local_path_seen_ = false;
      }
      map = pending_map_;
      global_path = global_path_;
      local_path = local_path_;
      odometry = odometry_;
    }

    if (map != nullptr) {
      const std::string version = mapVersion(*map);
      if (version != published_map_version_) {
        if (postJson("/api/internal/navigation/map", mapJson(*map, version))) {
          published_map_version_ = version;
          RCLCPP_INFO(
            get_logger(), "Navigation map uploaded: %ux%u version=%s",
            map->info.width, map->info.height, version.c_str());
        } else {
          RCLCPP_WARN_THROTTLE(
            get_logger(), *get_clock(), 5000, "Navigation map upload failed; backend unavailable");
        }
      }
    }

    const auto pose = currentPose();
    const auto global_points = pathPoints(global_path, max_global_path_points_);
    const auto local_points = pathPoints(local_path, max_local_path_points_);
    // Omni PID Pursuit exposes its controller path on /local_plan but does not publish a
    // separate /plan during NavigateToPose. In that case the transformed controller path is
    // the best available map-frame representation of the active global route.
    const auto & displayed_global_points = global_points.empty() ? local_points : global_points;
    if (!postJson(
        "/api/internal/navigation/state",
        snapshotJson(pose, displayed_global_points, local_points, odometry)))
    {
      // A backend restart clears its in-memory map cache. Force a map replay after reconnect.
      published_map_version_.clear();
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000, "Navigation state upload failed; backend unavailable");
    }
  }

  std::optional<Pose2D> currentPose()
  {
    try {
      const auto transform = tf_buffer_.lookupTransform(map_frame_, base_frame_, tf2::TimePointZero);
      const auto & translation = transform.transform.translation;
      const auto & rotation = transform.transform.rotation;
      return Pose2D{
        translation.x,
        translation.y,
        quaternionYaw(rotation.x, rotation.y, rotation.z, rotation.w)};
    } catch (const std::exception & error) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000, "Waiting for %s -> %s TF: %s",
        map_frame_.c_str(), base_frame_.c_str(), error.what());
      return std::nullopt;
    }
  }

  std::vector<Point2D> pathPoints(const nav_msgs::msg::Path::SharedPtr & path, int maximum)
  {
    std::vector<Point2D> points;
    if (path == nullptr || path->poses.empty()) {
      return points;
    }

    const std::string source_frame = path->header.frame_id.empty() ? map_frame_ : path->header.frame_id;
    double translation_x = 0.0;
    double translation_y = 0.0;
    double rotation_yaw = 0.0;
    if (source_frame != map_frame_) {
      try {
        const auto transform = tf_buffer_.lookupTransform(map_frame_, source_frame, tf2::TimePointZero);
        translation_x = transform.transform.translation.x;
        translation_y = transform.transform.translation.y;
        const auto & rotation = transform.transform.rotation;
        rotation_yaw = quaternionYaw(rotation.x, rotation.y, rotation.z, rotation.w);
      } catch (const std::exception & error) {
        RCLCPP_WARN_THROTTLE(
          get_logger(), *get_clock(), 5000, "Cannot transform %s path into %s: %s",
          source_frame.c_str(), map_frame_.c_str(), error.what());
        return points;
      }
    }
    const double cosine = std::cos(rotation_yaw);
    const double sine = std::sin(rotation_yaw);
    const auto to_map = [&](const auto & position) {
        return Point2D{
          translation_x + cosine * position.x - sine * position.y,
          translation_y + sine * position.x + cosine * position.y};
      };

    const size_t count = path->poses.size();
    const size_t stride = std::max<size_t>(1, (count + static_cast<size_t>(maximum) - 1) /
      static_cast<size_t>(maximum));
    points.reserve(std::min(count, static_cast<size_t>(maximum)) + 1);
    for (size_t index = 0; index < count; index += stride) {
      points.push_back(to_map(path->poses[index].pose.position));
    }
    const auto & last = path->poses.back().pose.position;
    const auto last_map = to_map(last);
    if (points.empty() || points.back().x != last_map.x || points.back().y != last_map.y) {
      points.push_back(last_map);
    }
    return points;
  }

  std::string snapshotJson(
    const std::optional<Pose2D> & pose,
    const std::vector<Point2D> & global_path,
    const std::vector<Point2D> & local_path,
    const nav_msgs::msg::Odometry::SharedPtr & odometry)
  {
    ++sequence_;
    double remaining = 0.0;
    if (pose.has_value() && !global_path.empty()) {
      Point2D previous{pose->x, pose->y};
      for (const auto & point : global_path) {
        remaining += std::hypot(point.x - previous.x, point.y - previous.y);
        previous = point;
      }
    }
    std::ostringstream stream;
    stream << std::setprecision(9)
           << "{\"source\":\"rk3588-ros2-navigation-web-bridge\","
           << "\"frame_id\":\"" << jsonEscape(map_frame_) << "\","
           << "\"timestamp\":\"" << utcTimestamp() << "\","
           << "\"sequence\":" << sequence_ << ','
           << "\"map_version\":";
    if (published_map_version_.empty()) {
      stream << "null";
    } else {
      stream << "\"" << published_map_version_ << "\"";
    }
    stream << ",\"pose\":";
    if (pose.has_value()) {
      stream << "{\"x\":" << pose->x << ",\"y\":" << pose->y << ",\"yaw\":" << pose->yaw << '}';
    } else {
      stream << "null";
    }
    stream << ",\"goal\":";
    if (!global_path.empty()) {
      const auto & goal = global_path.back();
      stream << "{\"x\":" << goal.x << ",\"y\":" << goal.y << ",\"yaw\":0.0}";
    } else {
      stream << "null";
    }
    stream << ",\"velocity\":";
    if (odometry != nullptr) {
      stream << "{\"vx\":" << odometry->twist.twist.linear.x
             << ",\"vy\":" << odometry->twist.twist.linear.y
             << ",\"wz\":" << odometry->twist.twist.angular.z << '}';
    } else {
      stream << "null";
    }
    appendPath(stream, "global_path", global_path);
    appendPath(stream, "local_path", local_path);
    stream << ",\"nav_state\":\""
           << (pose.has_value() ? (global_path.empty() ? "localized" : "navigating") : "waiting") << "\","
           << "\"remaining_distance\":";
    if (pose.has_value() && !global_path.empty()) {
      stream << remaining;
    } else {
      stream << "null";
    }
    stream << '}';
    return stream.str();
  }

  static void appendPath(
    std::ostringstream & stream, const std::string & name, const std::vector<Point2D> & points)
  {
    stream << ",\"" << name << "\":[";
    for (size_t index = 0; index < points.size(); ++index) {
      if (index > 0) {
        stream << ',';
      }
      stream << "{\"x\":" << points[index].x << ",\"y\":" << points[index].y << '}';
    }
    stream << ']';
  }

  std::string mapJson(const nav_msgs::msg::OccupancyGrid & map, const std::string & version) const
  {
    const auto & origin = map.info.origin;
    const auto & rotation = origin.orientation;
    std::ostringstream stream;
    stream << std::setprecision(9)
           << "{\"map_id\":\"" << jsonEscape(map_id_) << "\","
           << "\"version\":\"" << version << "\","
           << "\"frame_id\":\"" << jsonEscape(map.header.frame_id.empty() ? map_frame_ : map.header.frame_id) << "\","
           << "\"timestamp\":\"" << utcTimestamp() << "\","
           << "\"resolution\":" << map.info.resolution << ','
           << "\"width\":" << map.info.width << ','
           << "\"height\":" << map.info.height << ','
           << "\"origin\":{\"x\":" << origin.position.x
           << ",\"y\":" << origin.position.y
           << ",\"yaw\":" << quaternionYaw(rotation.x, rotation.y, rotation.z, rotation.w) << "},"
           << "\"data\":[";
    for (size_t index = 0; index < map.data.size(); ++index) {
      if (index > 0) {
        stream << ',';
      }
      stream << static_cast<int>(map.data[index]);
    }
    stream << "]}";
    return stream.str();
  }

  static std::string mapVersion(const nav_msgs::msg::OccupancyGrid & map)
  {
    std::ostringstream stream;
    stream << std::hex << fnv1a(map);
    return stream.str();
  }

  std::string backend_base_url_;
  std::string map_topic_;
  std::string global_path_topic_;
  std::string local_path_topic_;
  std::string odometry_topic_;
  std::string map_frame_;
  std::string base_frame_;
  std::string map_id_;
  double state_rate_hz_{10.0};
  int http_timeout_ms_{400};
  int max_global_path_points_{400};
  int max_local_path_points_{200};
  uint64_t sequence_{0};
  std::string published_map_version_;

  std::mutex data_mutex_;
  nav_msgs::msg::OccupancyGrid::SharedPtr pending_map_;
  nav_msgs::msg::Path::SharedPtr global_path_;
  nav_msgs::msg::Path::SharedPtr local_path_;
  nav_msgs::msg::Odometry::SharedPtr odometry_;
  std::chrono::steady_clock::time_point local_path_received_at_{};
  bool local_path_seen_{false};
  tf2_ros::Buffer tf_buffer_;
  tf2_ros::TransformListener tf_listener_;
  rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr map_subscription_;
  rclcpp::Subscription<nav_msgs::msg::Path>::SharedPtr global_path_subscription_;
  rclcpp::Subscription<nav_msgs::msg::Path>::SharedPtr local_path_subscription_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odometry_subscription_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv)
{
  curl_global_init(CURL_GLOBAL_DEFAULT);
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<NavigationWebBridge>());
  rclcpp::shutdown();
  curl_global_cleanup();
  return 0;
}
