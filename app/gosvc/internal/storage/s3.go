package storage

import (
	"context"
	"io"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

// S3 — Garage. S3 호환이라 minio-go 로 붙는다.
//
// Garage 는 리전 개념이 약하지만 서명 계산에 값이 필요하다. conf/garage.toml
// 의 s3_api.s3_region 과 같은 값을 넣어야 SignatureDoesNotMatch 가 안 난다.
type S3 struct {
	cli    *minio.Client
	bucket string
}

func NewS3(endpoint, accessKey, secretKey, bucket, region string, useSSL bool) (*S3, error) {
	c, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
		Region: region,
	})
	if err != nil {
		return nil, err
	}
	return &S3{cli: c, bucket: bucket}, nil
}

func (s *S3) Bucket() string { return s.bucket }

func (s *S3) Put(ctx context.Context, key string, r io.Reader, size int64, ct string) error {
	// size 가 음수면 minio 가 알아서 멀티파트로 올린다.
	_, err := s.cli.PutObject(ctx, s.bucket, key, r, size,
		minio.PutObjectOptions{ContentType: ct})
	return err
}

// Open — minio.Object 는 ReadSeekCloser 다. 그래서 http.ServeContent 에
// 그대로 넘길 수 있고, Range 요청이 저장소까지 그대로 전달된다.
func (s *S3) Open(ctx context.Context, key string) (ReadSeekCloser, *Info, error) {
	o, err := s.cli.GetObject(ctx, s.bucket, key, minio.GetObjectOptions{})
	if err != nil {
		return nil, nil, err
	}
	st, err := o.Stat()
	if err != nil {
		o.Close()
		return nil, nil, err
	}
	return o, &Info{Key: key, Size: st.Size, ContentType: st.ContentType,
		ETag: st.ETag, ModTime: st.LastModified}, nil
}

func (s *S3) Stat(ctx context.Context, key string) (*Info, error) {
	st, err := s.cli.StatObject(ctx, s.bucket, key, minio.StatObjectOptions{})
	if err != nil {
		return nil, err
	}
	return &Info{Key: key, Size: st.Size, ContentType: st.ContentType,
		ETag: st.ETag, ModTime: st.LastModified}, nil
}

func (s *S3) Delete(ctx context.Context, key string) error {
	return s.cli.RemoveObject(ctx, s.bucket, key, minio.RemoveObjectOptions{})
}
